"""The local HTTP API the web app (app/) talks to, over the SQLite database.

  shiftnet serve                          http://127.0.0.1:8000/api/…
  shiftnet serve --static ../app/dist     also serve the built app, so one process runs everything

The JSON shapes match what the app read from Supabase (PostgREST embeds and RPC results), so the
pages did not change. There is no sign-in: the one local user contributes and reviews.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, Response
from starlette.responses import JSONResponse as _JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import contributions as contrib
from . import db, lexicon

TOP_ATTESTATIONS = 3


class JSONResponse(_JSONResponse):
    """Dates (crawl dates of candidates and usages) as ISO strings."""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, separators=(",", ":"), default=str).encode()

# ---------- Lexicon ----------

_REF = "s.id, s.lemma, s.pos, s.sense_num, s.date_label, s.date_earliest, s.gloss"
_SENSE = f"""{_REF}, s.examples, s.obsolete_year, s.obsolete_label, s.shift, s.source, s.source_type,
  s.validation, s.branch"""


def _ref(r: dict, prefix: str = "") -> dict:
    return {k: r[prefix + k] for k in ("id", "lemma", "pos", "sense_num", "date_label", "date_earliest", "gloss")}


def _attach_links(conn: sqlite3.Connection, rows: list[dict]) -> list[dict]:
    """Add parents ([{position, source, parent: SenseRef}]) and synonyms ([{lemma, position}])."""
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    ph = db.placeholders(ids)
    parents: dict[str, list] = defaultdict(list)
    for p in conn.execute(
        f"""select sp.sense_id, sp.position, sp.source,
                   s.id as p_id, s.lemma as p_lemma, s.pos as p_pos, s.sense_num as p_sense_num,
                   s.date_label as p_date_label, s.date_earliest as p_date_earliest, s.gloss as p_gloss
            from sense_parents sp join senses s on s.id = sp.parent_id
            where sp.sense_id in ({ph}) order by sp.position""",
        ids,
    ):
        parents[p["sense_id"]].append({"position": p["position"], "source": p["source"], "parent": _ref(p, "p_")})
    synonyms: dict[str, list] = defaultdict(list)
    for l in conn.execute(f"select sense_id, lemma, position from sense_lemmas where sense_id in ({ph}) order by position", ids):
        synonyms[l["sense_id"]].append({"lemma": l["lemma"], "position": l["position"]})
    for r in rows:
        r["parents"] = parents[r["id"]]
        r["synonyms"] = synonyms[r["id"]]
    return rows


_RANKED = """
  select id, sense_id, quote, year, date_label, locator, relevance, validation, source as "source [JSON]",
         row_number() over (partition by sense_id order by source_rank > 1, relevance desc, year is null, year, id) as rank,
         count(*) over (partition by sense_id) as total
  from (
    select a.*,
      json_object('id', src.id, 'kind', src.kind, 'title', src.title, 'author', src.author, 'publisher', src.publisher,
                  'published_label', src.published_label, 'published_year', src.published_year, 'url', src.url,
                  'identifier', src.identifier, 'accessed_on', src.accessed_on) as source,
      row_number() over (partition by a.sense_id, a.source_id order by a.relevance desc, a.year is null, a.year, a.id) as source_rank
    from attestations a join sources src on src.id = a.source_id
    where a.sense_id in ({ids})
  )"""


def ranked_attestations(conn: sqlite3.Connection, sense_ids: list[str], max_rank: int | None = None) -> list[dict]:
    """Attestations in display order per sense: by relevance, but a work's second quotation comes after
    every other work's best one, so the top 3 are not three lines of the same book."""
    if not sense_ids:
        return []
    q = f"select * from ({_RANKED.format(ids=db.placeholders(sense_ids))})"
    params: list[Any] = list(sense_ids)
    if max_rank is not None:
        q += " where rank <= ?"
        params.append(max_rank)
    return conn.execute(q + " order by sense_id, rank", params).fetchall()


def words(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """select lemma, json_group_array(distinct pos) as "pos [JSON]", count(*) as sense_count, min(date_earliest) as first_year
           from senses group by lemma order by lemma limit 500"""
    ).fetchall()
    for r in rows:
        r["pos"].sort(key=db.POS_ORDER.index)
    return rows


def recent(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    rows = conn.execute(f"select {_SENSE} from senses s order by s.date_earliest desc, s.id limit ?", (limit,)).fetchall()
    return _attach_links(conn, rows)


def word(conn: sqlite3.Connection, lemma: str) -> list[dict]:
    """All senses of a head word, oldest first, each with its top attestations."""
    rows = _attach_links(conn, conn.execute(
        f"select {_SENSE} from senses s where s.lemma = ? order by s.date_earliest, s.id", (lemma,)
    ).fetchall())
    top: dict[str, list] = defaultdict(list)
    for a in ranked_attestations(conn, [r["id"] for r in rows], TOP_ATTESTATIONS):
        top[a["sense_id"]].append(a)
    for r in rows:
        r["top_attestations"] = top[r["id"]]
        r["attestation_count"] = top[r["id"]][0]["total"] if top[r["id"]] else 0
    return rows


def sense(conn: sqlite3.Connection, sense_id: str) -> dict | None:
    rows = _attach_links(conn, conn.execute(f"select {_SENSE}, s.synset_id from senses s where s.id = ?", (sense_id,)).fetchall())
    if not rows:
        return None
    rows[0]["relations"] = conn.execute(
        "select type, target_lemma, position from relations where sense_id = ? order by position", (sense_id,)
    ).fetchall()
    return rows[0]


def children(conn: sqlite3.Connection, sense_id: str) -> list[dict]:
    return conn.execute(
        f"""select {_REF} from sense_parents p join senses s on s.id = p.sense_id
            where p.parent_id = ? order by s.date_earliest, s.id""",
        (sense_id,),
    ).fetchall()


def attestation_years(conn: sqlite3.Connection, sense_ids: list[str]) -> list[dict]:
    if not sense_ids:
        return []
    return conn.execute(
        f"select sense_id, year from attestations where sense_id in ({db.placeholders(sense_ids)}) and year is not null",
        sense_ids,
    ).fetchall()


def resolve(conn: sqlite3.Connection, q: str) -> dict | None:
    """Exact lookup ignoring case and accents: a head word, else an expression's sense."""
    row = conn.execute("select 'word' as kind, lemma, null as sense_id from senses where lemma_key = normalize_lemma(?) limit 1",
                       (q,)).fetchone()
    return row or conn.execute(
        """select 'sense' as kind, l.lemma, l.sense_id from sense_lemmas l join senses s on s.id = l.sense_id
           where l.lemma_key = normalize_lemma(?) order by s.date_earliest, s.id limit 1""",
        (q,),
    ).fetchone()


# ---------- Taxonomy ----------

_SYNSET = "id, pos, lemmas, gloss"
_CARDS = """
  select y.id, y.pos, y.lemmas, y.gloss,
    (select count(*) from synset_hypernyms c where c.hypernym_id = y.id) as hyponym_count,
    (select count(*) from senses x where x.synset_id = y.id) as sense_count,
    (select min(x.date_earliest) from senses x where x.synset_id = y.id) as first_year,
    (select x.date_label from senses x where x.synset_id = y.id order by x.date_earliest, x.id limit 1) as first_label
  from synsets y"""


def synset(conn: sqlite3.Connection, synset_id: str) -> dict | None:
    row = conn.execute(f"select {_SYNSET} from synsets where id = ?", (synset_id,)).fetchone()
    if row is None:
        return None
    row["hypernyms"] = [
        {"position": h.pop("position"), "hypernym": h}
        for h in conn.execute(
            """select h.position, y.id, y.pos, y.lemmas, y.gloss from synset_hypernyms h join synsets y on y.id = h.hypernym_id
               where h.synset_id = ? order by h.position""",
            (synset_id,),
        )
    ]
    return row


def synset_path(conn: sqlite3.Connection, synset_id: str) -> list[dict]:
    """The synset and its ancestors along the first hypernym, root first; depth 0 is the synset itself."""
    return conn.execute(
        f"""with recursive up(depth, id, seen) as (
              select 0, id, json_array(id) from synsets where id = ?
              union all
              select up.depth + 1, h.hypernym_id, json_insert(up.seen, '$[#]', h.hypernym_id)
              from up join synset_hypernyms h on h.synset_id = up.id and h.position = 0
              where h.hypernym_id not in (select value from json_each(up.seen)) and up.depth < 50
            )
            select up.depth, y.id, y.pos, y.lemmas, y.gloss from up join synsets y on y.id = up.id order by up.depth desc""",
        (synset_id,),
    ).fetchall()


def synset_hyponyms(conn: sqlite3.Connection, synset_id: str) -> list[dict]:
    """Direct hyponyms, oldest dated sense first, then undated ones by name."""
    return conn.execute(
        f"""select * from ({_CARDS}) c
            where c.id in (select synset_id from synset_hypernyms where hypernym_id = ?)
            order by c.first_year is null, c.first_year, lower(c.lemmas ->> 0), c.id""",
        (synset_id,),
    ).fetchall()


def taxonomy_roots(conn: sqlite3.Connection) -> list[dict]:
    """Tops of the taxonomy: synsets with hyponyms but no hypernym."""
    return conn.execute(
        f"""select * from ({_CARDS}) c
            where c.hyponym_count > 0 and not exists (select 1 from synset_hypernyms h where h.synset_id = c.id)
            order by pos_order(c.pos), lower(c.lemmas ->> 0), c.id"""
    ).fetchall()


def synset_senses(conn: sqlite3.Connection, synset_id: str) -> list[dict]:
    return conn.execute(f"select {_REF} from senses s where s.synset_id = ? order by s.date_earliest, s.id", (synset_id,)).fetchall()


# ---------- Statistics (every figure about change uses the primary parent link, position 0) ----------


def _median(xs: list[int]) -> int | None:
    return round(statistics.median(xs)) if xs else None


def stats(conn: sqlite3.Connection) -> dict:
    senses = conn.execute("select id, lemma, pos, shift, date_earliest, obsolete_year from senses").fetchall()
    by_id = {s["id"]: s for s in senses}
    primary = {r["sense_id"]: by_id[r["parent_id"]]
               for r in conn.execute("select sense_id, parent_id from sense_parents where position = 0")}
    links = [(by_id[c], p) for c, p in primary.items()]

    overview = {
        "senses": len(senses),
        "words": len({s["lemma"] for s in senses}),
        "links": len(links),
        "obsolete": sum(s["obsolete_year"] is not None for s in senses),
        "pos_changes": sum(c["pos"] != p["pos"] for c, p in links),
        "cross_word": sum(c["lemma"] != p["lemma"] for c, p in links),
        "median_gap": _median([c["date_earliest"] - p["date_earliest"] for c, p in links]),
    }

    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for s in senses:
        groups[(db.period_label(s["date_earliest"]), s["shift"])].append(s["date_earliest"])
    start: dict[str, int] = {}
    for (period, _), years in groups.items():
        start[period] = min(start.get(period, years[0]), min(years))
    periods = sorted(
        ({"period": period, "period_start": start[period], "shift": shift, "senses": len(years)}
         for (period, shift), years in groups.items()),
        key=lambda r: (r["period_start"], db.SHIFT_ORDER.index(r["shift"])),
    )

    per_shift: dict[str, list[dict]] = defaultdict(list)
    for s in senses:
        per_shift[s["shift"]].append(s)
    shifts = []
    for shift in sorted(per_shift, key=db.SHIFT_ORDER.index):
        ss = per_shift[shift]
        gaps = [s["date_earliest"] - primary[s["id"]]["date_earliest"] for s in ss if s["id"] in primary]
        linked = [(s, primary[s["id"]]) for s in ss if s["id"] in primary]
        shifts.append({
            "shift": shift,
            "senses": len(ss),
            "obsolete": sum(s["obsolete_year"] is not None for s in ss),
            "median_gap": _median(gaps),
            "min_gap": min(gaps, default=None),
            "max_gap": max(gaps, default=None),
            "pos_changes": sum(c["pos"] != p["pos"] for c, p in linked),
            "cross_word": sum(c["lemma"] != p["lemma"] for c, p in linked),
        })

    counts: dict[tuple[str, str], int] = defaultdict(int)
    for c, p in links:
        counts[(p["pos"], c["pos"])] += 1
    transitions = [
        {"from_pos": f, "to_pos": t, "links": n}
        for (f, t), n in sorted(counts.items(), key=lambda x: (db.POS_ORDER.index(x[0][0]), db.POS_ORDER.index(x[0][1])))
    ]
    return {"overview": overview, "periods": periods, "shifts": shifts, "transitions": transitions}


# ---------- Discovery: candidate senses waiting for review ----------

_summary_cache: dict[str, tuple[float, list[dict]]] = {}
SUMMARY_TTL = 60  # seconds; reviews through this API clear it at once, CLI imports show up within a minute


def _word_summaries(conn: sqlite3.Connection) -> list[dict]:
    """One row per discovered word: candidates (all, pending), usages clustered, crawl span, whether it is a
    lexicon head word, and its frequency rank (bulk runs were imported most frequent word first)."""
    import time

    path = conn.execute("select file from pragma_database_list where name = 'main'").fetchone()["file"]
    hit = _summary_cache.get(path)
    if hit and time.monotonic() - hit[0] < SUMMARY_TTL:
        return hit[1]
    runs = {r["lemma_key"]: r for r in conn.execute(
        """select lemma_key, min(lemma) as lemma, sum(usage_count) as usages,
                  coalesce(min(case when bulk_tag is not null then rowid end), 1e18) as rank, min(rowid) as first
           from discovery_runs group by lemma_key"""
    )}
    cands = {r["lemma_key"]: r for r in conn.execute(
        """select lemma_key, count(*) as candidates, sum(status = 'pending') as pending,
                  min(first_seen) as first_seen, max(last_seen) as last_seen
           from sense_candidates group by lemma_key"""
    )}
    lexicon = {r["lemma_key"] for r in conn.execute("select distinct lemma_key from senses")}
    rows = []
    for i, (key, r) in enumerate(sorted(runs.items(), key=lambda kv: (kv[1]["rank"], kv[1]["first"])), 1):
        c = cands.get(key) or {}
        rows.append({
            "lemma": r["lemma"], "key": key, "rank": i, "usages": r["usages"],
            "candidates": c.get("candidates", 0), "pending": c.get("pending", 0),
            "first_seen": c.get("first_seen"), "last_seen": c.get("last_seen"), "in_lexicon": key in lexicon,
        })
    _summary_cache[path] = (time.monotonic(), rows)
    return rows


DISCOVERY_SORTS = {
    "frequent": lambda r: r["rank"],
    "alpha": lambda r: r["key"],
    "candidates": lambda r: (-r["candidates"], r["rank"]),
}


def discovery_words(conn: sqlite3.Connection, q: str = "", status: str = "pending", sort: str = "frequent",
                    offset: int = 0, limit: int = 100) -> dict:
    """Discovered words, filtered by a substring of the word and by whether candidates are still pending."""
    key = db.normalize_lemma(q) or ""
    rows = [r for r in _word_summaries(conn)
            if (not key or key in r["key"]) and (status != "pending" or r["pending"] > 0)]
    if key:  # words starting with the query first
        rows.sort(key=lambda r: (not r["key"].startswith(key), DISCOVERY_SORTS.get(sort, DISCOVERY_SORTS["frequent"])(r)))
    else:
        rows.sort(key=DISCOVERY_SORTS.get(sort, DISCOVERY_SORTS["frequent"]))
    total = len(_word_summaries(conn))
    pending_words = sum(r["pending"] > 0 for r in _word_summaries(conn))
    page = [{k: v for k, v in r.items() if k != "key"} for r in rows[offset : offset + limit]]
    return {"total_words": total, "pending_words": pending_words, "matches": len(rows), "words": page}


_USAGE = "id, context, target_start, target_end, url, crawled_on, dump, similarity"


def discovery_word(conn: sqlite3.Connection, lemma: str) -> dict | None:
    """A word's discovery runs and candidate senses, largest cluster first, each with its most typical and
    most borderline usages and the nearest existing sense."""
    runs = conn.execute(
        """select id, lemma, forms, corpus, dumps, model, usage_count, noise_count, started_at, bulk_tag
           from discovery_runs where lemma_key = normalize_lemma(?) order by started_at desc""",
        (lemma,),
    ).fetchall()
    if not runs:
        return None
    cands = conn.execute(
        f"""select c.id, c.run_id, c.cluster, c.size, c.status, c.terms, c.first_seen, c.last_seen, c.year_counts,
                   c.nearest_sense_id, c.nearest_score, c.sense_id, c.review_note, c.decided_at,
                   n.gloss as nearest_gloss, n.pos as nearest_pos, n.sense_num as nearest_sense_num
            from sense_candidates c left join senses n on n.id = c.nearest_sense_id
            where c.run_id in ({db.placeholders(runs)})
            order by c.status <> 'pending', c.size desc, c.cluster""",
        [r["id"] for r in runs],
    ).fetchall()
    for c in cands:
        c["typical_usages"] = conn.execute(
            f"select {_USAGE} from corpus_usages where candidate_id = ? order by similarity desc nulls last limit 15", (c["id"],)
        ).fetchall()
        shown = {u["id"] for u in c["typical_usages"]}
        c["borderline_usages"] = [u for u in conn.execute(
            f"select {_USAGE} from corpus_usages where candidate_id = ? order by similarity asc nulls last limit 5", (c["id"],)
        ) if u["id"] not in shown]
    return {"lemma": runs[0]["lemma"], "runs": runs, "candidates": cands}


def _review_candidate(fn: Callable[..., Any], *args: Any) -> Response:
    from pydantic import ValidationError

    from .discovery.store import ReviewError

    try:
        with db.transaction() as conn:
            ref = fn(conn, *args)
    except ReviewError as e:
        return JSONResponse({"message": str(e)}, status_code=409 if "already" in str(e) else 400)
    except ValidationError as e:
        return JSONResponse({"message": "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())},
                            status_code=400)
    _summary_cache.clear()
    return JSONResponse(ref.model_dump(mode="json"))


async def post_candidate(request: Request) -> Response:
    from .discovery.store import match, promote, reject
    from .models import PromoteIn, ValidationMethod

    cid, action = _p(request, "id"), _p(request, "action")
    body = await _body(request)
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected a JSON object")
    note = body.get("note") or None
    # Reviews from the web app are a person's decision: what they publish is validation 'manual'.
    if action == "match":
        return _review_candidate(match, cid, body.get("sense_id") or None, int(body.get("attestations", 3)), note,
                                 ValidationMethod.manual)
    if action == "promote":
        from pydantic import ValidationError

        try:
            p = PromoteIn.model_validate({**body, "validation": ValidationMethod.manual})
        except ValidationError as e:
            return JSONResponse({"message": "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())},
                                status_code=400)
        return _review_candidate(promote, cid, p)
    if action == "reject":
        return _review_candidate(reject, cid, note)
    raise HTTPException(404)


# ---------- HTTP ----------


def _read(fn: Callable[..., Any], *args: Any) -> JSONResponse:
    with db.reader() as conn:
        return JSONResponse(fn(conn, *args))


def _write(fn: Callable[..., Any], *args: Any) -> JSONResponse:
    try:
        with db.transaction() as conn:
            return JSONResponse(fn(conn, *args))
    except contrib.ChecksFailed as e:
        return JSONResponse({"message": str(e), "checks": e.checks}, status_code=e.status)
    except contrib.ContributionError as e:
        return JSONResponse({"message": str(e)}, status_code=e.status)


async def _body(request: Request) -> Any:
    try:
        return await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Expected a JSON body")


def _int(request: Request, name: str, default: int) -> int:
    try:
        return int(request.query_params.get(name, default))
    except ValueError:
        raise HTTPException(400, f"{name} must be a whole number")


def _p(request: Request, name: str) -> str:
    return request.path_params[name]


async def post_attestation_years(request: Request) -> Response:
    ids = (await _body(request)).get("ids") or []
    return _read(attestation_years, [str(i) for i in ids][:1000])


async def post_check(request: Request) -> Response:
    fn = {"usage": contrib.check_usage, "sense": contrib.check_sense, "relation": contrib.check_relation}.get(_p(request, "kind"))
    if fn is None:
        raise HTTPException(404)
    body = await _body(request)
    with db.reader() as conn:
        try:
            return JSONResponse(fn(conn, body))
        except contrib.ContributionError as e:
            return JSONResponse({"message": str(e)}, status_code=e.status)


async def post_submit(request: Request) -> Response:
    fn = {"usage": contrib.submit_usage, "sense": contrib.submit_sense, "relation": contrib.submit_relation}.get(_p(request, "kind"))
    if fn is None:
        raise HTTPException(404)
    return _write(fn, await _body(request))


async def post_review(request: Request) -> Response:
    body = await _body(request)
    return _write(contrib.review_contribution, _p(request, "id"), body.get("decision"), body.get("note"))


def _queue(request: Request) -> Response:
    try:
        return _read(contrib.queue, _p(request, "filter"))
    except contrib.ContributionError as e:
        return JSONResponse({"message": str(e)}, status_code=400)


routes = [
    Route("/api/words", lambda r: _read(words)),
    Route("/api/recent", lambda r: _read(recent, _int(r, "limit", 10))),
    Route("/api/word/{lemma:path}", lambda r: _read(word, _p(r, "lemma"))),
    Route("/api/sense/{id}", lambda r: _read(sense, _p(r, "id"))),
    Route("/api/sense/{id}/attestations", lambda r: _read(ranked_attestations, [_p(r, "id")])),
    Route("/api/sense/{id}/children", lambda r: _read(children, _p(r, "id"))),
    Route("/api/sense/{id}/pending-usages", lambda r: _read(contrib.pending_for_sense, _p(r, "id"))),
    Route("/api/sense/{id}/relation-suggestions", lambda r: _read(contrib.relation_suggestions, _p(r, "id"))),
    Route("/api/attestation-years", post_attestation_years, methods=["POST"]),
    Route("/api/search", lambda r: _read(lexicon.search_lemmas, r.query_params.get("q", ""), _int(r, "max", 8))),
    Route("/api/close-spellings", lambda r: _read(lexicon.close_spellings, r.query_params.get("q", ""), _int(r, "max", 5))),
    Route("/api/resolve", lambda r: _read(resolve, r.query_params.get("q", ""))),
    Route("/api/synset/{id}", lambda r: _read(synset, _p(r, "id"))),
    Route("/api/synset/{id}/path", lambda r: _read(synset_path, _p(r, "id"))),
    Route("/api/synset/{id}/hyponyms", lambda r: _read(synset_hyponyms, _p(r, "id"))),
    Route("/api/synset/{id}/senses", lambda r: _read(synset_senses, _p(r, "id"))),
    Route("/api/taxonomy/roots", lambda r: _read(taxonomy_roots)),
    Route("/api/stats", lambda r: _read(stats)),
    Route("/api/discovery/words", lambda r: _read(
        discovery_words, r.query_params.get("q", ""), r.query_params.get("status", "pending"),
        r.query_params.get("sort", "frequent"), _int(r, "offset", 0), min(_int(r, "limit", 100), 500))),
    Route("/api/discovery/word/{lemma:path}", lambda r: _read(discovery_word, _p(r, "lemma"))),
    Route("/api/discovery/candidates/{id}/{action}", post_candidate, methods=["POST"]),
    Route("/api/me", lambda r: JSONResponse({"id": contrib.LOCAL_USER, "moderator": True})),
    Route("/api/contributions", lambda r: _read(contrib.my_contributions)),
    Route("/api/contributions/queue/{filter}", _queue),
    Route("/api/contributions/check/{kind}", post_check, methods=["POST"]),
    Route("/api/contributions/{kind}", post_submit, methods=["POST"]),
    Route("/api/contributions/{id}/review", post_review, methods=["POST"]),
]


async def _http_error(request: Request, exc: HTTPException) -> Response:
    return JSONResponse({"message": exc.detail}, status_code=exc.status_code)


class _SPA(StaticFiles):
    """Serve the built app; unknown paths get index.html (routes are client-side: /word/cloud)."""

    async def get_response(self, path: str, scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code != 404 or path.startswith("api/"):
                raise
            return FileResponse(Path(self.directory) / "index.html")


def create_app(static: str | Path | None = None) -> Starlette:
    r = list(routes)
    if static:
        r.append(Mount("/", app=_SPA(directory=str(static), html=True)))
    return Starlette(routes=r, exception_handlers={HTTPException: _http_error})


def serve(host: str = "127.0.0.1", port: int = 8000, static: str | Path | None = None) -> None:
    import uvicorn

    with db.reader():  # create the database now, and fail early on a bad path
        pass
    uvicorn.run(create_app(static), host=host, port=port)
