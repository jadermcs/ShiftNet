"""Proposing WordNet relations for a sense with LexSPLADE.

LexSPLADE turns a marked word in context into a weighted list of vocabulary terms. Two readings of
that list give relation candidates:

  synonyms   the sense's own vector (its examples, quotes and gloss, target marked) lists words that
             could stand in its place. A candidate is kept when putting it in those contexts gives a
             vector close to the original one (a substitution test).
             The test cannot tell a synonym from a sister term (mouse → rat, cat), so these are
             near-synonyms for a person to sort.
  hypernyms, meronyms
             a [MASK] slot in a definitional pattern that carries the gloss, e.g.
             "a mouse (a small rodent …) is a kind of <t> [MASK] </t>", lists words for the slot.
             A term counts when it weighs more in its slot than in the sense's own vector and in the
             other slot: generic fillers (surface, system) are strong in every slot and cancel out.
             Hypernyms must also pass the substitution test ("a <animal> ran under the stove").
  hyponyms, holonyms
             are not probed (the patterns return sister terms and noise); they are the inverses of
             hypernyms and meronyms found for other senses of ShiftNet.

Only whole words of the encoder's vocabulary can be proposed: a word split into pieces (rodent →
rod ##ent) never comes out.

Open English WordNet (the `wn` package, lexicon oewn:2024) is used only to lemmatise terms
(rodents → rodent) and to keep terms of the sense's part of speech; the proposals come from the model.
Suggestions are evidence for a reviewer, never published on their own.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np
from scipy import sparse

from ..models import CorpusUsage
from .encoder import Encoder, normalize_rows
from .text import default_forms, forms_pattern, occurrences

WN_POS = {"noun": "n", "verb": "v", "adjective": "a", "adverb": "r"}

# Patterns per part of speech: {w} lemma, {g} gloss, {b} gloss without its leading article. The slot is the marked [MASK].
TEMPLATES: dict[str, dict[str, list[str]]] = {
    "noun": {
        "hypernym": [
            "a {w} ({g}) is a kind of <t> [MASK] </t> .",
            "<t> [MASK] </t> , such as a {w} ({g}) .",
            "a {b} is a kind of <t> [MASK] </t> .",  # the gloss alone, so a metaphorical sense is not read literally
        ],
        "meronym": [
            "a <t> [MASK] </t> is a part of a {w} ({g}) .",
            "the {w} ({g}) has a <t> [MASK] </t> .",
        ],
    },
    "verb": {
        "hypernym": [
            "to {w} ({g}) is a way to <t> [MASK] </t> .",
            "to {w} is to <t> [MASK] </t> in a particular way ({g}) .",
            "to {b} is a way to <t> [MASK] </t> .",
        ],
    },
    "adjective": {},
    "adverb": {},
}
INVERSE = {"hypernym": "hyponym", "meronym": "holonym"}
RELATIONS = ("synonym", "hypernym", "hyponym", "meronym", "holonym")


@dataclass
class SenseInfo:
    id: str
    lemma: str
    pos: str
    gloss: str
    texts: list[str] = field(default_factory=list)  # examples and attestation quotes
    known: set[tuple[str, str]] = field(default_factory=set)  # (type, target) already recorded, synonyms included


@dataclass
class Suggestion:
    sense_id: str
    type: str
    target_lemma: str
    score: float  # 0–1
    evidence: dict
    target_sense_id: str | None = None
    target_score: float | None = None
    target_synset_id: str | None = None  # a taxonomy synset without a dated sense


class WordFilter:
    """Lemmatise vocabulary terms and keep those that are mainly of one part of speech."""

    def __init__(self, lexicon: str = "oewn:2024"):
        try:
            import wn
            from wn.morphy import Morphy

            base = wn.Wordnet(lexicon)
            self.wn = wn.Wordnet(lexicon, lemmatizer=Morphy(base))
        except Exception:  # wn not installed or lexicon not downloaded: fall back to the raw term
            self.wn = None
        self._cache: dict[tuple[str, str], str | None] = {}

    def lemma(self, term: str, pos: str) -> str | None:
        key = (term, pos)
        if key not in self._cache:
            self._cache[key] = self._lemma(term, pos)
        return self._cache[key]

    def _lemma(self, term: str, pos: str) -> str | None:
        if len(term) < 3 or not term.isalpha():
            return None
        if self.wn is None:
            return term
        want = WN_POS[pos]
        counts: dict[str, int] = {}
        best: dict[str, str] = {}
        for w in self.wn.words(term):
            p = "a" if w.pos == "s" else w.pos
            n = len(w.synsets())
            counts[p] = counts.get(p, 0) + n
            if p == want and (p not in best or w.lemma() == term):
                best[p] = w.lemma()
        if want not in counts or counts[want] < 0.8 * max(counts.values()):
            return None  # not mainly a word of this part of speech ("small" is rarely a noun, "water" rarely a verb)
        lemma = best[want]
        return lemma if lemma == lemma.lower() else None  # proper names (Key, Apple) are not relations


class RelationSuggester:
    def __init__(self, encoder: Encoder, words: WordFilter | None = None, per_relation: int = 6, pool: int = 40):
        self.enc = encoder
        self.words = words or WordFilter()
        self.per_relation = per_relation
        self.pool = pool

    # ---------- vectors ----------

    def _encode_marked(self, texts: list[str]) -> sparse.csr_matrix:
        """Encode sentences that already carry <t> … </t>."""
        usages = []
        for t in texts:
            a, b = t.index("<t> "), t.index(" </t>")
            ctx = t[:a] + t[a + 4 : b] + t[b + 5 :]
            usages.append(CorpusUsage(doc_id="probe", context=ctx, target_start=a, target_end=b - 4))
        return self.enc.encode(usages, show_progress=False)

    def _contexts(self, s: SenseInfo) -> list[CorpusUsage]:
        """The gloss as a definitional sentence, plus examples and quotes where the lemma occurs."""
        defn = f"{s.lemma}: {s.gloss}."
        out = [CorpusUsage(doc_id=s.id, context=defn, target_start=0, target_end=len(s.lemma))]
        pattern = forms_pattern(default_forms(s.lemma) + [s.lemma])
        for text in s.texts:
            for o in occurrences(text, pattern, self.enc.count_tokens, self.enc.max_tokens, max_per_doc=1, min_words=1):
                out.append(CorpusUsage(doc_id=s.id, context=o.context, target_start=o.start, target_end=o.end))
        return out[:6]

    @staticmethod
    def _mean(m: sparse.csr_matrix) -> np.ndarray:
        v = np.asarray(m.mean(axis=0)).ravel()
        n = np.linalg.norm(v)
        return v / n if n else v

    def _substitution(self, contexts: list[CorpusUsage], base: np.ndarray, terms: list[str]) -> dict[str, float]:
        """Cosine between the sense vector and the vector of each term put in the sense's contexts."""
        if not terms:
            return {}
        subs, owner = [], []
        for t in terms:
            for c in contexts:
                ctx = c.context[: c.target_start] + t + c.context[c.target_end :]
                subs.append(CorpusUsage(doc_id="sub", context=ctx, target_start=c.target_start, target_end=c.target_start + len(t)))
                owner.append(t)
        V = self.enc.encode(subs, show_progress=False)
        out = {}
        for t in terms:
            rows = [i for i, o in enumerate(owner) if o == t]
            out[t] = float(self._mean(V[rows]) @ base)
        return out

    def _candidates(self, v: np.ndarray, s: SenseInfo, exclude: set[str]) -> list[tuple[str, float, str]]:
        """(lemma, weight, vocabulary term) for the strongest usable terms of a vector."""
        out, seen = [], set()
        for i in np.argsort(-v)[: self.pool]:
            if v[i] <= 0:
                break
            term = self.enc.vocab[i]
            lemma = self.words.lemma(term, s.pos)
            if not lemma or lemma in seen or lemma in exclude:
                continue
            seen.add(lemma)
            out.append((lemma, float(v[i]), term))
        return out

    # ---------- suggestions ----------

    def suggest(self, s: SenseInfo) -> list[Suggestion]:
        forms = {f.lower() for f in default_forms(s.lemma)} | {s.lemma.lower()}
        exclude = forms | {w for f in forms for w in f.split()}
        contexts = self._contexts(s)
        base = self._mean(self.enc.encode(contexts, show_progress=False))
        out: list[Suggestion] = []

        # Synonyms: substitutes for the sense, checked by putting them back in its contexts.
        cands = [c for c in self._candidates(base, s, exclude) if ("synonym", c[0]) not in s.known][: self.per_relation * 2]
        subst = self._substitution(contexts, base, [c[0] for c in cands])
        for lemma, w, term in cands:
            score = 0.9 * float(np.sqrt(min(1.0, w / 0.25) * max(0.0, subst[lemma])))
            out.append(Suggestion(s.id, "synonym", lemma, round(score, 4),
                                  {"method": "substitutes", "weight": round(w, 4), "substitution": round(subst[lemma], 4), "term": term}))

        # Pattern relations: what a slot adds over the sense's own profile and over the other slot.
        templates = TEMPLATES.get(s.pos, {})
        slots = {
            r: self._mean(self._encode_marked([t.format(w=s.lemma, g=s.gloss, b=_bare(s.gloss)) for t in ts])) for r, ts in templates.items()
        }
        zero = np.zeros_like(base)
        for r, slot in slots.items():
            others = [v for k, v in slots.items() if k != r]
            rival = np.maximum.reduce([*others, base if r == "hypernym" else zero])
            spec = slot - rival
            cands = [c for c in self._candidates(slot, s, exclude) if (r, c[0]) not in s.known]
            cands = [c for c in cands if spec[self.enc.vocab.index(c[2])] > 0][: self.per_relation]
            sub = self._substitution(contexts, base, [c[0] for c in cands]) if r == "hypernym" else {}
            for lemma, w, term in cands:
                d = float(spec[self.enc.vocab.index(term)])
                if r == "hypernym":
                    if sub[lemma] < 0.6:
                        continue
                    score = float(np.sqrt(min(1.0, d / 0.08)) * sub[lemma])
                else:
                    score = 0.9 * min(1.0, d / 0.1)
                ev = {"method": "pattern", "slot": round(w, 4), "specificity": round(d, 4), "term": term}
                if r == "hypernym":
                    ev["substitution"] = round(sub[lemma], 4)
                out.append(Suggestion(s.id, r, lemma, round(score, 4), ev))
        # A near-synonym that is really a broader term is reported as a hypernym only.
        broader = {x.target_lemma for x in out if x.type == "hypernym"}
        out = [x for x in out if not (x.type == "synonym" and x.target_lemma in broader)]
        out.sort(key=lambda x: (RELATIONS.index(x.type), -x.score))
        return out

    def link_targets(
        self,
        suggestions: list[Suggestion],
        senses_by_lemma: dict[str, list[SenseInfo]],
        sources: dict[str, SenseInfo],
        synsets_by_lemma: dict[str, list[SenseInfo]] | None = None,
    ) -> None:
        """Pick, for each suggestion whose target is in ShiftNet, the sense (or taxonomy synset) that fits
        best: the one whose definitional vector is closest to the slot's vector (the sense's own vector
        for synonyms). synsets_by_lemma holds synsets with no dated sense, as SenseInfo with the synset id."""
        for sg in suggestions:
            src = sources[sg.sense_id]
            same_pos = sg.type not in ("meronym", "holonym")
            options = [t for t in senses_by_lemma.get(sg.target_lemma, []) if not same_pos or t.pos == src.pos]
            synsets = [t for t in (synsets_by_lemma or {}).get(sg.target_lemma, []) if not same_pos or t.pos == src.pos]
            if not options and not synsets:
                continue
            both = options + synsets
            probe = self._probe_for(src, sg.type)
            V = self.enc.encode(
                [CorpusUsage(doc_id=t.id, context=f"{sg.target_lemma}: {t.gloss or sg.target_lemma}.", target_start=0,
                             target_end=len(sg.target_lemma)) for t in both],
                show_progress=False,
            )
            sims = (normalize_rows(V) @ probe).ravel()
            best = int(np.argmax(sims))
            if best < len(options):
                sg.target_sense_id = both[best].id
            else:
                sg.target_synset_id = both[best].id
            sg.target_score = round(float(sims[best]), 4)

    def _probe_for(self, s: SenseInfo, rel: str) -> np.ndarray:
        templates = TEMPLATES.get(s.pos, {}).get(rel)
        if templates:
            return self._mean(self._encode_marked([t.format(w=s.lemma, g=s.gloss, b=_bare(s.gloss)) for t in templates]))
        return self._mean(self.enc.encode(self._contexts(s), show_progress=False))


def _bare(gloss: str) -> str:
    """'a small rodent …' → 'small rodent …', 'to make unclear' → 'make unclear'."""
    return re.sub(r"^(a|an|the|to)\s+", "", gloss.strip(), flags=re.I)


def inverses(suggestions: Iterable[Suggestion], senses: dict[str, SenseInfo]) -> list[Suggestion]:
    """hypernym(A → sense B) gives hyponym(B → A); holonym(A → B) gives meronym(B → A)."""
    out = []
    for sg in suggestions:
        inv = INVERSE.get(sg.type)
        if not inv or not sg.target_sense_id or sg.target_sense_id not in senses:
            continue
        src = senses[sg.sense_id]
        target = senses[sg.target_sense_id]
        if (inv, src.lemma) in target.known:
            continue
        score = round(sg.score * (sg.target_score or 0) ** 0.5, 4)
        out.append(Suggestion(target.id, inv, src.lemma, score,
                              {"method": "inverse", "of": sg.type, "from": src.id, "score": sg.score}, src.id, sg.target_score))
    return out


