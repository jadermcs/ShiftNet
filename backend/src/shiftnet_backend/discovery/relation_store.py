"""Loading senses for relation suggestions and storing what the model proposes.

Suggestions land in relation_suggestions, where the Contribute page offers them and the
automatic checks for a proposed relation use them as evidence. Each run replaces the suggestions of
the senses it covered.
"""

from __future__ import annotations

from typing import Any

import sqlite3

from .. import db
from .relations import RelationSuggester, SenseInfo, Suggestion, inverses


def load_senses(conn: sqlite3.Connection, quotes: int = 4) -> dict[str, SenseInfo]:
    """Every sense, with its examples, best quotes and what is already recorded (relations, synonyms,
    pending relation contributions), so known relations are not suggested again."""
    rows = conn.execute(
        """select s.id, s.lemma, s.pos, s.gloss, s.examples,
             (select json_group_array(quote) from (select a.quote from attestations a where a.sense_id = s.id
                   order by a.relevance desc limit ?)) as "quotes [JSON]",
             (select json_group_array(k) from (
                select r.type || '|' || lower(r.target_lemma) as k from relations r where r.sense_id = s.id
                union all select 'synonym|' || lower(l.lemma) from sense_lemmas l where l.sense_id = s.id
                union all select (k.payload ->> 'type') || '|' || lower(k.payload ->> 'target_lemma')
                          from contributions k
                          where k.sense_id = s.id and k.kind = 'relation' and k.status <> 'rejected')) as "known [JSON]"
           from senses s""",
        (quotes,),
    ).fetchall()
    return {
        r["id"]: SenseInfo(
            r["id"], r["lemma"], r["pos"], r["gloss"], [*r["examples"], *r["quotes"]],
            {tuple(k.split("|", 1)) for k in r["known"]},
        )
        for r in rows
    }


def load_synsets(conn: sqlite3.Connection) -> dict[str, list[SenseInfo]]:
    """Taxonomy synsets with no dated sense, by member word: targets for hypernyms such as animal."""
    rows = conn.execute(
        """select y.id, y.pos, y.gloss, m.value as lemma
           from synsets y, json_each(y.lemmas) m
           where not exists (select 1 from senses s where s.synset_id = y.id)"""
    ).fetchall()
    out: dict[str, list[SenseInfo]] = {}
    for r in rows:
        out.setdefault(r["lemma"].lower(), []).append(SenseInfo(r["id"], r["lemma"], r["pos"], r["gloss"] or ""))
    return out


def suggest(
    conn: sqlite3.Connection, suggester: RelationSuggester, lemmas: list[str] | None = None,
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


def save_suggestions(conn: sqlite3.Connection, suggestions: list[Suggestion], model: str, covered: set[str]) -> int:
    """Replace the model's suggestions for the covered senses; inverse suggestions for other senses are
    upserted. Returns the number stored."""
    covered = list(covered)
    for i in range(0, len(covered), 500):
        chunk = covered[i : i + 500]
        conn.execute(f"delete from relation_suggestions where sense_id in ({db.placeholders(chunk)}) and model = ?", [*chunk, model])
    conn.executemany(
        """insert into relation_suggestions
             (sense_id, type, target_lemma, target_sense_id, target_synset_id, target_score, score, evidence, model)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?)
           on conflict (sense_id, type, target_key) do update set
             target_sense_id = excluded.target_sense_id, target_synset_id = excluded.target_synset_id,
             target_score = excluded.target_score,
             score = max(relation_suggestions.score, excluded.score),
             evidence = excluded.evidence, model = excluded.model, created_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
        [
            (x.sense_id, x.type, x.target_lemma, x.target_sense_id, x.target_synset_id, x.target_score, min(1.0, max(0.0, x.score)),
             x.evidence, model)
            for x in suggestions
        ],
    )
    return len(suggestions)


def list_suggestions(conn: sqlite3.Connection, sense_id: str) -> list[dict[str, Any]]:
    return conn.execute(
        """select r.type, r.target_lemma, r.target_sense_id, r.target_synset_id,
                  coalesce(t.gloss, y.gloss) as target_gloss, r.score, r.evidence
           from relation_suggestions r
           left join senses t on t.id = r.target_sense_id
           left join synsets y on y.id = r.target_synset_id
           where r.sense_id = ? order by r.type, r.score desc""",
        (sense_id,),
    ).fetchall()
