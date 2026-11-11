"""Reading and writing the lexicon: senses, parent links, synset members, relations, sources and
attestations. Every function takes an open connection and leaves committing to the caller (see
db.transaction), so a batch either lands whole or not at all.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from . import db
from .models import AttestationIn, PartOfSpeech, SenseIn, SourceIn, sense_id_prefix

# ---------- Writing ----------


def next_sense_id(conn: sqlite3.Connection, lemma: str, pos: PartOfSpeech | str) -> str:
    """Next free id for a lemma and part of speech: cloud.n.07. Writers hold SQLite's write lock
    (db.transaction begins immediate), so two of them never pick the same id."""
    prefix = sense_id_prefix(lemma, pos)
    rows = conn.execute(
        "select substr(id, ?) as rest from senses where substr(id, 1, ?) = ?", (len(prefix) + 1, len(prefix), prefix)
    ).fetchall()
    n = max((int(r["rest"]) for r in rows if re.fullmatch(r"\d+", r["rest"])), default=0)
    return f"{prefix}{n + 1:02d}"


def source_for(conn: sqlite3.Connection, s: SourceIn | dict) -> str:
    """Reuse a cited work with the same URL, else the same identifier, else (with neither) the same
    kind, title and author; otherwise insert it."""
    d = s.model_dump(mode="json") if isinstance(s, SourceIn) else dict(s)
    for k in ("author", "publisher", "published_label", "published_year", "url", "identifier", "accessed_on"):
        d.setdefault(k, None)
    row = conn.execute(
        """select id from sources src
           where (:url is not null and lower(src.url) = lower(:url))
              or (:identifier is not null and lower(src.identifier) = lower(:identifier))
              or (:url is null and :identifier is null
                  and src.kind = :kind
                  and normalize_lemma(src.title) = normalize_lemma(:title)
                  and coalesce(normalize_lemma(src.author), '') = coalesce(normalize_lemma(:author), ''))
           order by (:url is not null and lower(src.url) = lower(:url)) desc, src.created_at
           limit 1""",
        d,
    ).fetchone()
    if row:
        return row["id"]
    return conn.execute(
        """insert into sources (kind, title, author, publisher, published_label, published_year, url, identifier, accessed_on)
           values (:kind, :title, :author, :publisher, :published_label, :published_year, :url, :identifier, :accessed_on)
           returning id""",
        d,
    ).fetchone()["id"]


def add_attestation(conn: sqlite3.Connection, sense_id: str, a: AttestationIn) -> str:
    """Quote a usage for a sense. The same quote from the same work is stored once."""
    source_id = source_for(conn, a.source)
    existing = conn.execute(
        """select id from attestations
           where sense_id = ? and source_id = ? and normalize_lemma(quote) = normalize_lemma(?)""",
        (sense_id, source_id, a.quote),
    ).fetchone()
    if existing:
        return existing["id"]
    validation = a.validation.value if hasattr(a.validation, "value") else a.validation
    att = conn.execute(
        """insert into attestations
             (sense_id, source_id, quote, year, date_label, locator, relevance_override, validation, validated_at)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?)
           returning id""",
        (sense_id, source_id, a.quote, a.year, a.date_label, a.locator, a.relevance_override, validation,
         db.now() if validation != "editorial" else None),
    ).fetchone()["id"]
    db.refresh_relevance(conn, [att])
    return att


def save_senses(conn: sqlite3.Connection, senses: list[SenseIn]) -> list[str]:
    """Insert or update senses with their parents, synset members, relations and attestations.

    A sense with an existing id is updated: its parents, synonyms and relations are replaced by the
    ones given, and attestations are added (never removed). A sense without an id gets the next free
    one. Rows are written before links, so parents may come later in the same batch.
    Returns the ids, in input order.
    """
    ids: list[str] = []
    for s in senses:
        sid = s.id or next_sense_id(conn, s.lemma, s.pos)
        conn.execute(
            """insert into senses
                 (id, lemma, pos, gloss, examples, date_label, date_earliest, obsolete_year, obsolete_label,
                  shift, source, source_type, validation)
               values (:id, :lemma, :pos, :gloss, :examples, :date_label, :date_earliest,
                       :obsolete_year, :obsolete_label, :shift, :source, :source_type, :validation)
               on conflict (id) do update set
                 lemma = excluded.lemma, pos = excluded.pos, gloss = excluded.gloss, examples = excluded.examples,
                 date_label = excluded.date_label, date_earliest = excluded.date_earliest,
                 obsolete_year = excluded.obsolete_year, obsolete_label = excluded.obsolete_label,
                 shift = excluded.shift, source = excluded.source, source_type = excluded.source_type,
                 validation = excluded.validation""",
            {**s.model_dump(mode="json", exclude={"parents", "synonyms", "relations", "attestations"}), "id": sid},
        )
        ids.append(sid)

    for sid, s in zip(ids, senses):
        conn.execute("delete from sense_parents where sense_id = ?", (sid,))
        conn.executemany(
            "insert into sense_parents (sense_id, parent_id, position, source) values (?, ?, ?, ?)",
            [(sid, p.parent_id, i, p.source) for i, p in enumerate(s.parents)],
        )
        conn.execute("delete from sense_lemmas where sense_id = ?", (sid,))
        members = list(dict.fromkeys([s.lemma, *s.synonyms]))
        conn.executemany(
            "insert into sense_lemmas (sense_id, lemma, position) values (?, ?, ?)",
            [(sid, lemma, i) for i, lemma in enumerate(members)],
        )
        conn.execute("delete from relations where sense_id = ?", (sid,))
        conn.executemany(
            "insert into relations (sense_id, type, target_lemma, position) values (?, ?, ?, ?) on conflict do nothing",
            [(sid, r.type.value if hasattr(r.type, "value") else r.type, r.target_lemma, i) for i, r in enumerate(s.relations)],
        )
    # Foreign keys are checked per statement, so a parent later in the batch must already be written:
    # it is, since every sense row went in above.
    db.renumber_senses(conn)
    for sid, s in zip(ids, senses):
        for a in s.attestations:
            add_attestation(conn, sid, a)
    return ids


# ---------- Reading ----------


def search_lemmas(conn: sqlite3.Connection, q: str, max_results: int = 8) -> list[dict[str, Any]]:
    """Suggestions: head words and multi-word expressions / synonyms that contain the query."""
    key = db.normalize_lemma(q) or ""
    if len(key) < 2:
        return []
    pattern = "%" + key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    heads = [
        {"lemma": r["lemma"], "kind": "word", "sense_id": None,
         "pos": " · ".join(sorted(set(r["pos"]), key=db.POS_ORDER.index)),
         "meta": f"{r['n']} sense" + ("" if r["n"] == 1 else "s"),
         "score": 0 if r["lemma_key"].startswith(key) else 1}
        for r in conn.execute(
            r"""select lemma, min(lemma_key) as lemma_key, json_group_array(pos) as "pos [JSON]", count(*) as n
                from senses where lemma_key like ? escape '\' group by lemma""",
            (pattern,),
        )
    ]
    expressions = conn.execute(
        r"""select lemma, 'sense' as kind, sense_id, pos, 'sense of ' || head as meta,
                   case when substr(lemma_key, 1, length(:q)) = :q then 0 else 2 end as score
            from (
              select l.lemma, l.lemma_key, s.id as sense_id, s.pos, s.lemma as head,
                     row_number() over (partition by l.lemma_key order by s.date_earliest, s.id) as rn
              from sense_lemmas l join senses s on s.id = l.sense_id
              where l.lemma_key like :pattern escape '\'
                and not exists (select 1 from senses h where h.lemma_key = l.lemma_key)
            ) where rn = 1""",
        {"q": key, "pattern": pattern},
    ).fetchall()
    rows = sorted(heads + expressions, key=lambda r: (r["score"], r["lemma"]))[:max_results]
    return [{k: r[k] for k in ("lemma", "kind", "sense_id", "pos", "meta")} for r in rows]


def close_spellings(conn: sqlite3.Connection, q: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Close spellings for a query with no match (edit distance up to a third of its length, at least 2)."""
    key = db.normalize_lemma(q) or ""
    if not key:
        return []
    max_d = max(2, -(-len(key) // 3))
    candidates = [
        {"lemma": r["lemma"], "kind": "word", "sense_id": None, "key": r["lemma_key"]}
        for r in conn.execute("select distinct lemma, lemma_key from senses")
    ] + [
        {"lemma": r["lemma"], "kind": "sense", "sense_id": r["sense_id"], "key": r["lemma_key"]}
        for r in conn.execute(
            """select lemma, lemma_key, sense_id from (
                 select l.lemma, l.lemma_key, l.sense_id,
                        row_number() over (partition by l.lemma_key order by l.lemma, l.sense_id) as rn
                 from sense_lemmas l
                 where not exists (select 1 from senses h where h.lemma_key = l.lemma_key)
               ) where rn = 1"""
        )
    ]
    scored = []
    for c in candidates:
        if abs(len(c["key"]) - len(key)) > max_d:
            continue
        d = db.levenshtein(key, c["key"])
        if d <= max_d:
            scored.append((d, c["lemma"], {k: c[k] for k in ("lemma", "kind", "sense_id")}))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [x[2] for x in scored[:max_results]]


def search(conn: sqlite3.Connection, q: str, limit: int = 8) -> list[dict[str, Any]]:
    rows = search_lemmas(conn, q, limit)
    if rows:
        return rows
    return [{**r, "close_spelling": True} for r in close_spellings(conn, q)]


def _sense_rows(conn: sqlite3.Connection, where: str, params: tuple) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""select s.id, s.lemma, s.pos, s.sense_num, s.gloss, s.examples, s.date_label, s.date_earliest,
                   s.obsolete_year, s.obsolete_label, s.shift, s.source, s.source_type, s.validation, s.branch
            from senses s where {where} order by s.date_earliest, s.id""",
        params,
    ).fetchall()
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    ph = db.placeholders(ids)
    parents: dict[str, list] = {}
    for p in conn.execute(
        f"""select p.sense_id, p.parent_id as id, ps.lemma, ps.gloss, p.position, p.source
            from sense_parents p join senses ps on ps.id = p.parent_id
            where p.sense_id in ({ph}) order by p.position""",
        ids,
    ):
        parents.setdefault(p.pop("sense_id"), []).append(p)
    synonyms: dict[str, list] = {}
    for l in conn.execute(
        f"""select l.sense_id, l.lemma from sense_lemmas l join senses s on s.id = l.sense_id
            where l.sense_id in ({ph}) and l.lemma <> s.lemma order by l.position""",
        ids,
    ):
        synonyms.setdefault(l["sense_id"], []).append(l["lemma"])
    for r in rows:
        r["parents"] = parents.get(r["id"], [])
        r["synonyms"] = synonyms.get(r["id"], [])
    return rows


def word(conn: sqlite3.Connection, lemma: str) -> list[dict[str, Any]]:
    """A head word's senses in registration order, with parents and synonyms."""
    rows = _sense_rows(conn, "s.lemma_key = normalize_lemma(?)", (lemma,))
    for r in rows:
        r["attestation_count"] = conn.execute(
            "select count(*) as n from attestations where sense_id = ?", (r["id"],)
        ).fetchone()["n"]
    return rows


def sense(conn: sqlite3.Connection, sense_id: str, attestations: int = 10) -> dict[str, Any] | None:
    """One sense with its children, relations and most relevant attestations."""
    rows = _sense_rows(conn, "s.id = ?", (sense_id,))
    if not rows:
        return None
    row = rows[0]
    row["children"] = conn.execute(
        """select c.id, c.lemma, c.gloss, c.date_label from sense_parents p
           join senses c on c.id = p.sense_id where p.parent_id = ? order by c.date_earliest, c.id""",
        (sense_id,),
    ).fetchall()
    row["relations"] = conn.execute(
        "select type, target_lemma from relations where sense_id = ? order by type, position", (sense_id,)
    ).fetchall()
    row["attestations"] = conn.execute(
        """select a.id, a.quote, a.year, a.date_label, a.locator, a.validation, a.relevance,
                  json_object('kind', src.kind, 'title', src.title, 'author', src.author, 'url', src.url) as "source [JSON]"
           from attestations a join sources src on src.id = a.source_id
           where a.sense_id = ? order by a.relevance desc, a.year is null, a.year limit ?""",
        (sense_id, attestations),
    ).fetchall()
    return row


def sense_texts(conn: sqlite3.Connection, lemma: str, per_sense: int = 8) -> dict[str, list[str]]:
    """Examples and attestation quotes per sense of a word, used to tell discovered clusters apart
    from senses already in the lexicon."""
    out: dict[str, list[str]] = {}
    for r in conn.execute("select id, examples from senses where lemma_key = normalize_lemma(?)", (lemma,)).fetchall():
        quotes = [q["quote"] for q in conn.execute(
            "select quote from attestations where sense_id = ? order by relevance desc limit ?", (r["id"], per_sense)
        )]
        out[r["id"]] = [*r["examples"], *quotes][:per_sense]
    return out
