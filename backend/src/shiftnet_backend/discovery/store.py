"""Storing discovery runs and reviewing their candidates.

Review outcomes:
  match    the cluster is a sense already in the lexicon; its most typical usages can be quoted
           as attestations of that sense
  promote  the cluster is a new sense; it is written to senses with a reviewer's gloss,
           dated by the earliest crawl it was seen in, with its most typical usages as attestations
  reject   noise, a mix of senses, or not worth recording
"""

from __future__ import annotations

import sqlite3
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from ..lexicon import add_attestation, save_senses
from ..models import (
    AttestationIn,
    CandidateRef,
    CandidateStatus,
    ParentIn,
    PromoteIn,
    ReferenceKind,
    RunResult,
    SenseIn,
    ShiftType,
    SourceIn,
    SourceType,
    ValidationMethod,
)


class ReviewError(ValueError):
    pass


def save_run(conn: sqlite3.Connection, r: RunResult) -> UUID:
    run_id = conn.execute(
        """insert into discovery_runs (lemma, forms, corpus, dumps, model, params, usage_count, noise_count, finished_at)
           values (?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) returning id""",
        (
            r.lemma, r.forms, r.corpus, r.dumps, r.model, r.params,
            len(r.usages) if r.usage_count is None else r.usage_count,
            r.assignments.count(-1) if r.noise_count is None else r.noise_count,
        ),
    ).fetchone()["id"]

    cand_ids: dict[int, UUID] = {}
    for c in r.candidates:
        cand_ids[c.cluster] = conn.execute(
            """insert into sense_candidates
                 (run_id, cluster, lemma, size, terms, first_seen, last_seen, year_counts, nearest_sense_id, nearest_score)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) returning id""",
            (
                run_id, c.cluster, r.lemma, c.size, [t.model_dump() for t in c.terms], c.first_seen,
                c.last_seen, c.year_counts, c.nearest_sense_id, c.nearest_score,
            ),
        ).fetchone()["id"]

    conn.executemany(
        """insert into corpus_usages
             (run_id, candidate_id, doc_id, dump, url, crawled_on, context, target_start, target_end, similarity, terms)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           on conflict do nothing""",
        [
            (
                run_id, cand_ids.get(label), u.doc_id, u.dump, u.url, u.crawled_on, u.context, u.target_start,
                u.target_end, sim, [t.model_dump() for t in terms],
            )
            for u, label, sim, terms in zip(r.usages, r.assignments, r.similarities, r.usage_terms)
        ],
    )
    return run_id


def list_candidates(
    conn: sqlite3.Connection, lemma: str | None = None, status: CandidateStatus | None = CandidateStatus.pending,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return conn.execute(
        """select c.id, c.run_id, c.cluster, c.lemma, c.size, c.status,
                  (select json_group_array(term) from (select t.value ->> 'term' as term from json_each(c.terms) t limit 8)) as "terms [JSON]",
                  c.first_seen, c.last_seen, c.nearest_sense_id, c.nearest_score, s.gloss as nearest_gloss, c.sense_id,
                  c.created_at
           from sense_candidates c left join senses s on s.id = c.nearest_sense_id
           where (:lemma is null or c.lemma_key = normalize_lemma(:lemma))
             and (:status is null or c.status = :status)
           order by c.created_at desc, c.cluster
           limit :limit""",
        {"lemma": lemma, "status": status, "limit": limit},
    ).fetchall()


def get_candidate(conn: sqlite3.Connection, candidate_id: UUID | str, usages: int = 10) -> dict[str, Any] | None:
    """A candidate with its most typical usages (closest to the centroid) and a few borderline ones."""
    c = conn.execute(
        """select c.*, s.gloss as nearest_gloss, r.forms, r.dumps, r.params
           from sense_candidates c
           join discovery_runs r on r.id = c.run_id
           left join senses s on s.id = c.nearest_sense_id
           where c.id = ?""",
        (str(candidate_id),),
    ).fetchone()
    if c is None:
        return None
    cols = "id, context, target_start, target_end, url, crawled_on, dump, similarity"
    c["typical_usages"] = conn.execute(
        f"select {cols} from corpus_usages where candidate_id = ? order by similarity desc nulls last limit ?",
        (c["id"], usages),
    ).fetchall()
    c["borderline_usages"] = conn.execute(
        f"select {cols} from corpus_usages where candidate_id = ? order by similarity asc nulls last limit ?",
        (c["id"], max(1, usages // 3)),
    ).fetchall()
    return c


def _pending(conn: sqlite3.Connection, candidate_id: UUID | str) -> dict[str, Any]:
    c = conn.execute(
        "select * from sense_candidates where id = ?", (str(candidate_id),)
    ).fetchone()
    if c is None:
        raise ReviewError(f"No candidate {candidate_id}")
    if c["status"] != CandidateStatus.pending:
        raise ReviewError(f"Candidate {candidate_id} is already {c['status']}")
    return c


def _top_usages(conn: sqlite3.Connection, candidate_id: UUID, n: int) -> list[dict[str, Any]]:
    if n <= 0:
        return []
    return conn.execute(
        """select id, context, url, crawled_on, dump from corpus_usages
           where candidate_id = ? and attestation_id is null
           order by similarity desc nulls last limit ?""",
        (candidate_id, n),
    ).fetchall()


def usage_attestation(
    u: dict[str, Any], corpus: str, validation: ValidationMethod = ValidationMethod.automatic
) -> AttestationIn:
    """A corpus usage as an attestation: the web page is the cited work, the crawl date stands in for
    its date (the page existed by then). validation: automatic when a model or script picked it, manual
    when a person reviewed the candidate."""
    host = urlsplit(u["url"]).hostname if u.get("url") else None
    crawled = u.get("crawled_on")
    source = (
        SourceIn(kind=ReferenceKind.website, title=host, publisher=host, url=u["url"], accessed_on=crawled)
        if host
        else SourceIn(kind=ReferenceKind.corpus, title=corpus, identifier=u.get("dump"))
    )
    return AttestationIn(
        quote=u["context"],
        source=source,
        year=crawled.year if crawled else None,
        date_label=f"by {crawled.isoformat()}" if crawled else None,
        validation=validation,
    )


def _quote(
    conn: sqlite3.Connection, sense_id: str, usages: list[dict[str, Any]], corpus: str, validation: ValidationMethod
) -> list[UUID]:
    out = []
    for u in usages:
        att = add_attestation(conn, sense_id, usage_attestation(u, corpus, validation))
        conn.execute("update corpus_usages set attestation_id = ? where id = ?", (att, u["id"]))
        out.append(att)
    return out


def _decide(conn, candidate_id, status: CandidateStatus, sense_id: str | None, note: str | None) -> CandidateRef:
    row = conn.execute(
        """update sense_candidates set status = ?, sense_id = ?, review_note = ?, decided_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
           where id = ? returning id, status, sense_id""",
        (status, sense_id, note, str(candidate_id)),
    ).fetchone()
    return CandidateRef(**row)


def _corpus(conn, run_id: UUID) -> str:
    return conn.execute("select corpus from discovery_runs where id = ?", (run_id,)).fetchone()["corpus"]


def match(
    conn: sqlite3.Connection, candidate_id: UUID | str, sense_id: str | None = None, attestations: int = 3,
    note: str | None = None, validation: ValidationMethod = ValidationMethod.automatic,
) -> CandidateRef:
    """The cluster is an existing sense (the nearest one unless sense_id is given). Its quoted usages get
    `validation`: automatic (the default, for the assistant / CLI flow) or manual (a person reviewed it)."""
    c = _pending(conn, candidate_id)
    sense_id = sense_id or c["nearest_sense_id"]
    if not sense_id:
        raise ReviewError("No sense given and the candidate has no nearest sense")
    if not conn.execute("select 1 from senses where id = ?", (sense_id,)).fetchone():
        raise ReviewError(f"No sense {sense_id}")
    _quote(conn, sense_id, _top_usages(conn, c["id"], attestations), _corpus(conn, c["run_id"]), validation)
    return _decide(conn, c["id"], CandidateStatus.matched, sense_id, note)


def promote(conn: sqlite3.Connection, candidate_id: UUID | str, p: PromoteIn) -> CandidateRef:
    """Write the cluster to the lexicon as a new sense of its lemma."""
    c = _pending(conn, candidate_id)
    if c["first_seen"] is None and p.date_earliest is None:
        raise ReviewError("The candidate has no crawl dates: give date_earliest and date_label")
    year = p.date_earliest or c["first_seen"].year
    usages = _top_usages(conn, c["id"], max(p.examples, p.attestations))
    corpus = _corpus(conn, c["run_id"])
    first = conn.execute(
        "select dump from corpus_usages where candidate_id = ? and crawled_on = ? limit 1",
        (c["id"], c["first_seen"]),
    ).fetchone()
    sense = SenseIn(
        lemma=c["lemma"],
        pos=p.pos,
        gloss=p.gloss,
        examples=[u["context"] for u in usages[: p.examples]],
        date_label=p.date_label or str(year),
        date_earliest=year,
        shift=p.shift or (ShiftType.other if p.parent_ids else ShiftType.root),
        source=(
            f"{corpus}, earliest of {c['size']} clustered usages"
            + (f" (crawl {first['dump']}, {c['first_seen'].isoformat()})" if first and first["dump"] else "")
        ),
        source_type=SourceType.corpus,
        validation=p.validation,
        parents=[ParentIn(parent_id=pid, source=f"sense discovery, candidate {c['id']}") for pid in p.parent_ids],
    )
    (sense_id,) = save_senses(conn, [sense])
    _quote(conn, sense_id, usages[: p.attestations], corpus, p.validation)
    return _decide(conn, c["id"], CandidateStatus.promoted, sense_id, p.note)


def reject(conn: sqlite3.Connection, candidate_id: UUID | str, note: str | None = None) -> CandidateRef:
    c = _pending(conn, candidate_id)
    return _decide(conn, c["id"], CandidateStatus.rejected, None, note)
