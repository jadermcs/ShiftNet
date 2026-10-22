"""Loading senses for relation suggestions and storing what the model proposes.

Suggestions land in public.relation_suggestions, where the Contribute page offers them and the
automatic checks for a proposed relation use them as evidence. Each run replaces the suggestions of
the senses it covered.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .relations import RelationSuggester, SenseInfo, Suggestion, inverses


def load_senses(conn: psycopg.Connection, quotes: int = 4) -> dict[str, SenseInfo]:
    """Every sense, with its examples, best quotes and what is already recorded (relations, synonyms,
    pending relation contributions), so known relations are not suggested again."""
    rows = conn.execute(
        """select s.id, s.lemma, s.pos::text as pos, s.gloss, s.examples,
             array(select a.quote from public.attestations a where a.sense_id = s.id
                   order by a.relevance desc limit %s) as quotes,
             array(select r.type::text || '|' || lower(r.target_lemma) from public.relations r where r.sense_id = s.id)
             || array(select 'synonym|' || lower(l.lemma) from public.sense_lemmas l where l.sense_id = s.id)
             || array(select (k.payload ->> 'type') || '|' || lower(k.payload ->> 'target_lemma')
                      from public.contributions k
                      where k.sense_id = s.id and k.kind::text = 'relation' and k.status <> 'rejected') as known
           from public.senses s""",
        (quotes,),
    ).fetchall()
    return {
        r["id"]: SenseInfo(
            r["id"], r["lemma"], r["pos"], r["gloss"], [*r["examples"], *r["quotes"]],
            {tuple(k.split("|", 1)) for k in r["known"]},
        )
        for r in rows
    }


def load_synsets(conn: psycopg.Connection) -> dict[str, list[SenseInfo]]:
    """Taxonomy synsets with no dated sense, by member word: targets for hypernyms such as animal."""
    rows = conn.execute(
        """select y.id, y.pos::text as pos, y.gloss, m as lemma
           from public.synsets y, unnest(y.lemmas) m
           where not exists (select 1 from public.senses s where s.synset_id = y.id)"""
    ).fetchall()
    out: dict[str, list[SenseInfo]] = {}
    for r in rows:
        out.setdefault(r["lemma"].lower(), []).append(SenseInfo(r["id"], r["lemma"], r["pos"], r["gloss"] or ""))
    return out


def suggest(
    conn: psycopg.Connection, suggester: RelationSuggester, lemmas: list[str] | None = None,
    min_score: float = 0.2,
) -> list[Suggestion]:
    """Suggestions for every sense of the given lemmas (all senses when None), plus the inverse
    relations they imply for other senses (a hypernym found for mouse is a hyponym of animal)."""
    senses = load_senses(conn)
    synsets = load_synsets(conn)
    wanted = {l.lower() for l in lemmas} if lemmas else None
    by_lemma: dict[str, list[SenseInfo]] = {}
    for s in senses.values():
        by_lemma.setdefault(s.lemma.lower(), []).append(s)

    out: list[Suggestion] = []
    for s in senses.values():
        if wanted is not None and s.lemma.lower() not in wanted:
            continue
        found = suggester.suggest(s)
        suggester.link_targets(found, by_lemma, senses, synsets)
        out.extend(found)
    out.extend(inverses(out, senses))
    return [x for x in out if x.score >= min_score]


def save_suggestions(conn: psycopg.Connection, suggestions: list[Suggestion], model: str, covered: set[str]) -> int:
    """Replace the model's suggestions for the covered senses; inverse suggestions for other senses are
    upserted. Returns the number stored."""
    conn.execute("delete from public.relation_suggestions where sense_id = any(%s) and model = %s", (list(covered), model))
    with conn.cursor() as cur:
        cur.executemany(
            """insert into public.relation_suggestions
                 (sense_id, type, target_lemma, target_sense_id, target_synset_id, target_score, score, evidence, model)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               on conflict (sense_id, type, public.normalize_lemma(target_lemma)) do update set
                 target_sense_id = excluded.target_sense_id, target_synset_id = excluded.target_synset_id,
                 target_score = excluded.target_score,
                 score = greatest(public.relation_suggestions.score, excluded.score),
                 evidence = excluded.evidence, model = excluded.model, created_at = now()""",
            [
                (x.sense_id, x.type, x.target_lemma, x.target_sense_id, x.target_synset_id, x.target_score, min(1.0, max(0.0, x.score)),
                 Jsonb(x.evidence), model)
                for x in suggestions
            ],
        )
    return len(suggestions)


def list_suggestions(conn: psycopg.Connection, sense_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """select r.type, r.target_lemma, r.target_sense_id, r.target_synset_id,
                  coalesce(t.gloss, y.gloss) as target_gloss, r.score, r.evidence
           from public.relation_suggestions r
           left join public.senses t on t.id = r.target_sense_id
           left join public.synsets y on y.id = r.target_synset_id
           where r.sense_id = %s order by r.type, r.score desc""",
        (sense_id,),
    ).fetchall()
