"""Lemmatising the word forms of a corpus, learning from the corpus itself.

Forms are lemmatised once per type, not per token: a few hundred thousand types instead of billions
of tokens.

- Dictionary words: WordNet's morphy knows their inflections, regular and irregular (mice → mouse,
  went → go).
- Every other form (selfies, doomscrolling, vaping): suffix rules are learnt from the forms morphy
  could reduce. Each pair gives a rule (running → run: strip "ning"), supported by how many types
  show it. An unknown form takes the rule whose output is the most frequent word of the corpus
  (selfies → selfie, not selfy). It keeps its own form when no rule gives an attested word.
- Ambiguous forms (leaves → leaf | leave; saw → saw | see) keep every candidate. Which lemma a given
  usage belongs to is decided later, in context, by comparing its LexSPLADE vector with each
  candidate's unambiguous usages (bulk.resolve).
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass

log = logging.getLogger(__name__)

Morphy = Callable[[str], dict[str, set[str]]]  # form → {pos: lemmas}

# Closed-class words: they have no senses worth clustering.
FUNCTION_WORDS = frozenset(
    """
    a about above across after afterwards again against all almost alone along already also although
    always am among amongst an and another any anybody anyhow anyone anything anyway anywhere are
    around as at be because been before beforehand behind being below beside besides between beyond
    both but by can cannot could did do does doing done down during each either else elsewhere enough
    etc even ever every everybody everyone everything everywhere except few for from further had has
    have having he hence her here hereafter hereby herein hers herself him himself his how however i
    if in indeed inside into is it its itself just least less many may me meanwhile might mine more
    moreover most mostly much must my myself neither never nevertheless next no nobody none noone nor
    not nothing now nowhere of off often on once one only onto or other others otherwise our ours
    ourselves out over own per perhaps quite rather same shall she should since so some somebody
    somehow someone something sometime sometimes somewhere still such than that the their theirs them
    themselves then thence there thereafter thereby therefore therein thereupon these they this those
    though through throughout thru thus to together too toward towards under unless until up upon us
    very via was we were what whatever when whence whenever where whereafter whereas whereby wherein
    whereupon wherever whether which while whither who whoever whole whom whose why will with within
    without would yet you your yours yourself yourselves
    """.split()
)


@dataclass
class Lemmas:
    of: dict[str, tuple[str, ...]]  # form → candidate lemmas, most frequent first
    dictionary: frozenset[str]  # lemmas morphy knows
    rules: list[tuple[str, str, int]]  # learnt (strip, add, supporting types), best first

    def ambiguous(self, form: str) -> bool:
        return len(self.of.get(form, ())) > 1


def wordnet_morphy(lexicon: str = "oewn:2024") -> Morphy | None:
    """WordNet's morphy, or None when the wn package or the lexicon is missing."""
    try:
        import wn
        from wn.morphy import Morphy as _Morphy

        return _Morphy(wn.Wordnet(lexicon))
    except Exception as e:  # noqa: BLE001 - any failure means: no dictionary
        log.warning("WordNet unavailable (%s): every form is lemmatised by learnt rules", e)
        return None


def _rule(form: str, lemma: str) -> tuple[str, str] | None:
    """running → run gives ("ning", ""); leaves → leaf gives ("ves", "f"). Suppletive pairs (went → go,
    mice → mouse) share too little to generalise and give none."""
    p = len(os.path.commonprefix([form, lemma]))
    if p < 2 or p == len(form):
        return None
    return form[p:], lemma[p:]


def learn(
    counts: Mapping[str, int],
    morphy: Morphy | None,
    min_count: int = 5,
    min_support: int = 20,
    min_ratio: float = 0.1,
    min_stem: int = 3,
) -> Lemmas:
    """Lemmas of every form seen at least min_count times.

    A learnt rule needs min_support types behind it. An unknown form reduced by a rule needs its lemma
    attested at least min_count times and at least min_ratio as often as the form itself, and the
    stem left after stripping must be min_stem letters or more.
    """
    of: dict[str, set[str]] = {}
    dictionary: set[str] = set()
    unknown: list[str] = []
    support: Counter[tuple[str, str]] = Counter()
    for form, n in counts.items():
        if n < min_count:
            continue
        if form in FUNCTION_WORDS:  # morphy reads "after" as a comparative of "aft"
            of[form] = {form}
            continue
        found = morphy(form) if morphy else None
        if not found:
            unknown.append(form)
            continue
        lemmas = {l for ls in found.values() for l in ls if " " not in l and "_" not in l}
        if not lemmas:
            unknown.append(form)
            continue
        of[form] = lemmas
        dictionary |= lemmas
        for l in lemmas:
            if r := _rule(form, l):
                support[r] += 1

    rules = [(s, a, n) for (s, a), n in support.most_common() if n >= min_support]
    by_strip: dict[str, list[str]] = {}
    for s, a, _ in rules:
        by_strip.setdefault(s, []).append(a)
    lengths = sorted({len(s) for s in by_strip})
    for form in unknown:
        best, best_n = form, 0
        floor = max(min_count, min_ratio * counts[form])
        for k in lengths:
            if len(form) - k < min_stem:
                break
            for add in by_strip.get(form[-k:], ()):
                lemma = form[:-k] + add
                n = counts.get(lemma, 0)
                if lemma != form and n >= floor and n > best_n:
                    best, best_n = lemma, n
        of[form] = {best}
    log.info("%d forms: %d in WordNet, %d learnt rules, %d reduced by rule", len(of), len(of) - len(unknown),
             len(rules), sum(1 for f in unknown if of[f] != {f}))
    family: Counter[str] = Counter()  # occurrences of all the forms that can reduce to a lemma
    for f, ls in of.items():
        for l in ls:
            family[l] += counts[f]
    return Lemmas(
        {f: tuple(sorted(ls, key=lambda l: (-family[l], l))) for f, ls in of.items()},
        frozenset(dictionary),
        rules,
    )


def vocabulary(
    lemmas: Lemmas,
    counts: Mapping[str, int],
    capitalised: Mapping[str, int],
    top: int,
    min_length: int = 3,
    max_capitalised: float = 0.5,
    dictionary_only: bool = False,
) -> list[tuple[str, float]]:
    """The `top` most frequent content lemmas with their counts. An ambiguous form's count is split
    evenly among its lemmas. Function words, non-alphabetic lemmas and mostly capitalised ones
    (proper names: more than max_capitalised of their occurrences) are left out."""
    total: Counter[str] = Counter()
    caps: Counter[str] = Counter()
    for form, ls in lemmas.of.items():
        share = 1 / len(ls)
        for l in ls:
            total[l] += counts.get(form, 0) * share
            caps[l] += capitalised.get(form, 0) * share
    keep = [
        (l, n) for l, n in total.items()
        if len(l) >= min_length and l.isascii() and l.isalpha() and l.islower() and l not in FUNCTION_WORDS
        and caps[l] <= max_capitalised * n and (not dictionary_only or l in lemmas.dictionary)
    ]
    keep.sort(key=lambda t: (-t[1], t[0]))
    return keep[:top]
