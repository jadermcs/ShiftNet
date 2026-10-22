"""Reading and writing the public lexicon: senses, parent links, synset members, relations,
sources and attestations. Every function takes an open connection and leaves committing to the
caller (see db.transaction), so a batch either lands whole or not at all.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg

from .models import AttestationIn, PartOfSpeech, SenseIn, SourceIn, sense_id_prefix

# ---------- Writing ----------


def next_sense_id(conn: psycopg.Connection, lemma: str, pos: PartOfSpeech) -> str:
    """Next free id for a lemma and part of speech: cloud.n.07.

    Same rule and same advisory lock as private.next_sense_id, so ids made here never collide
    with a contribution published at the same time.
    """
    prefix = sense_id_prefix(lemma, pos)
    conn.execute("select pg_advisory_xact_lock(hashtext(%s))", ("shiftnet.sense_id:" + prefix,))
    row = conn.execute(
        r"""select coalesce(max(substr(id, length(%(p)s) + 1)::integer), 0) + 1 as n
            from public.senses
            where left(id, length(%(p)s)) = %(p)s and substr(id, length(%(p)s) + 1) ~ '^\d+$'""",
        {"p": prefix},
    ).fetchone()
    return f"{prefix}{row['n']:02d}"


def source_for(conn: psycopg.Connection, s: SourceIn) -> UUID:
    """Reuse a cited work with the same URL, else the same identifier, else (with neither) the same
    kind, title and author; otherwise insert it. Same rule as private.source_for."""
    row = conn.execute(
        """select id from public.sources src
           where (%(url)s::text is not null and lower(src.url) = lower(%(url)s))
              or (%(identifier)s::text is not null and lower(src.identifier) = lower(%(identifier)s))
              or (%(url)s::text is null and %(identifier)s::text is null
                  and src.kind::text = %(kind)s
                  and public.normalize_lemma(src.title) = public.normalize_lemma(%(title)s)
                  and coalesce(public.normalize_lemma(src.author), '') = coalesce(public.normalize_lemma(%(author)s), ''))
           order by (%(url)s::text is not null and lower(src.url) = lower(%(url)s)) desc, src.created_at
           limit 1""",
        s.model_dump(mode="json"),
    ).fetchone()
    if row:
        return row["id"]
    return conn.execute(
        """insert into public.sources (kind, title, author, publisher, published_label, published_year, url, identifier, accessed_on)
           values (%(kind)s, %(title)s, %(author)s, %(publisher)s, %(published_label)s, %(published_year)s, %(url)s, %(identifier)s, %(accessed_on)s)
           returning id""",
        s.model_dump(mode="json"),
    ).fetchone()["id"]


def add_attestation(conn: psycopg.Connection, sense_id: str, a: AttestationIn) -> UUID:
    """Quote a usage for a sense. The same quote from the same work is stored once."""
    source_id = source_for(conn, a.source)
    existing = conn.execute(
        """select id from public.attestations
           where sense_id = %s and source_id = %s and public.normalize_lemma(quote) = public.normalize_lemma(%s)""",
        (sense_id, source_id, a.quote),
    ).fetchone()
    if existing:
        return existing["id"]
    return conn.execute(
        """insert into public.attestations
             (sense_id, source_id, quote, year, date_label, locator, relevance_override, validation, validated_at)
           values (%s, %s, %s, %s, %s, %s, %s, %s, case when %s <> 'editorial' then now() end)
           returning id""",
        (sense_id, source_id, a.quote, a.year, a.date_label, a.locator, a.relevance_override, a.validation, a.validation),
    ).fetchone()["id"]


def save_senses(conn: psycopg.Connection, senses: list[SenseIn]) -> list[str]:
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
            """insert into public.senses
                 (id, lemma, pos, gloss, examples, date_label, date_earliest, obsolete_year, obsolete_label,
                  shift, source, source_type, validation)
               values (%(id)s, %(lemma)s, %(pos)s, %(gloss)s, %(examples)s, %(date_label)s, %(date_earliest)s,
                       %(obsolete_year)s, %(obsolete_label)s, %(shift)s, %(source)s, %(source_type)s, %(validation)s)
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
        conn.execute("delete from public.sense_parents where sense_id = %s", (sid,))
        for i, p in enumerate(s.parents):
            conn.execute(
                "insert into public.sense_parents (sense_id, parent_id, position, source) values (%s, %s, %s, %s)",
                (sid, p.parent_id, i, p.source),
            )
        conn.execute("delete from public.sense_lemmas where sense_id = %s", (sid,))
        members = list(dict.fromkeys([s.lemma, *s.synonyms]))
        for i, lemma in enumerate(members):
            conn.execute(
                "insert into public.sense_lemmas (sense_id, lemma, position) values (%s, %s, %s)", (sid, lemma, i)
            )
        conn.execute("delete from public.relations where sense_id = %s", (sid,))
        for i, r in enumerate(s.relations):
            conn.execute(
                """insert into public.relations (sense_id, type, target_lemma, position) values (%s, %s, %s, %s)
                   on conflict do nothing""",
                (sid, r.type, r.target_lemma, i),
            )
        for a in s.attestations:
            add_attestation(conn, sid, a)
    return ids


# ---------- Reading ----------


def search(conn: psycopg.Connection, q: str, limit: int = 8) -> list[dict[str, Any]]:
    rows = conn.execute("select * from public.search_lemmas(%s, %s)", (q, limit)).fetchall()
    if rows:
        return rows
    return [{**r, "close_spelling": True} for r in conn.execute("select * from public.close_spellings(%s)", (q,))]


_SENSE_COLUMNS = """s.id, s.lemma, s.pos, s.sense_num, s.gloss, s.examples, s.date_label, s.date_earliest,
  s.obsolete_year, s.obsolete_label, s.shift, s.source, s.source_type, s.validation, s.branch,
  coalesce((select jsonb_agg(jsonb_build_object('id', p.parent_id, 'lemma', ps.lemma, 'gloss', ps.gloss,
                                                'position', p.position, 'source', p.source) order by p.position)
            from public.sense_parents p join public.senses ps on ps.id = p.parent_id
            where p.sense_id = s.id), '[]') as parents,
  array(select l.lemma from public.sense_lemmas l where l.sense_id = s.id and l.lemma <> s.lemma order by l.position) as synonyms"""


def word(conn: psycopg.Connection, lemma: str) -> list[dict[str, Any]]:
    """A head word's senses in registration order, with parents and synonyms."""
    return conn.execute(
        f"""select {_SENSE_COLUMNS},
              (select count(*) from public.attestations a where a.sense_id = s.id)::integer as attestation_count
            from public.senses s
            where public.normalize_lemma(s.lemma) = public.normalize_lemma(%s)
            order by s.date_earliest, s.id""",
        (lemma,),
    ).fetchall()


def sense(conn: psycopg.Connection, sense_id: str, attestations: int = 10) -> dict[str, Any] | None:
    """One sense with its children, relations and most relevant attestations."""
    row = conn.execute(f"select {_SENSE_COLUMNS} from public.senses s where s.id = %s", (sense_id,)).fetchone()
    if row is None:
        return None
    row["children"] = conn.execute(
        """select c.id, c.lemma, c.gloss, c.date_label from public.sense_parents p
           join public.senses c on c.id = p.sense_id where p.parent_id = %s order by c.date_earliest, c.id""",
        (sense_id,),
    ).fetchall()
    row["relations"] = conn.execute(
        "select type, target_lemma from public.relations where sense_id = %s order by type, position", (sense_id,)
    ).fetchall()
    row["attestations"] = conn.execute(
        """select a.id, a.quote, a.year, a.date_label, a.locator, a.validation, a.relevance,
                  jsonb_build_object('kind', src.kind, 'title', src.title, 'author', src.author, 'url', src.url) as source
           from public.attestations a join public.sources src on src.id = a.source_id
           where a.sense_id = %s order by a.relevance desc, a.year nulls last limit %s""",
        (sense_id, attestations),
    ).fetchall()
    return row


def sense_texts(conn: psycopg.Connection, lemma: str, per_sense: int = 8) -> dict[str, list[str]]:
    """Examples and attestation quotes per sense of a word, used to tell discovered clusters apart
    from senses already in the lexicon."""
    rows = conn.execute(
        """select s.id, s.gloss, s.examples,
             array(select a.quote from public.attestations a where a.sense_id = s.id
                   order by a.relevance desc limit %s) as quotes
           from public.senses s
           where public.normalize_lemma(s.lemma) = public.normalize_lemma(%s)""",
        (per_sense, lemma),
    ).fetchall()
    return {r["id"]: [*r["examples"], *r["quotes"]][:per_sense] for r in rows}

