"""ShiftNet MCP server: lets an assistant browse the lexicon and review discovered senses.

Read tools are always on. Tools that write (saving senses, running discovery, reviewing
candidates) are only registered when SHIFTNET_MCP_WRITE=1, since DATABASE_URL is privileged.

  DATABASE_URL=postgresql://… SHIFTNET_MCP_WRITE=1 shiftnet-mcp            # stdio
  shiftnet-mcp --transport streamable-http                                 # http://127.0.0.1:8000/mcp
"""

from __future__ import annotations

import argparse
import json
import os
from functools import lru_cache
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import db, lexicon
from .models import AttestationIn, CandidateStatus, PromoteIn, SenseIn

WRITE = os.environ.get("SHIFTNET_MCP_WRITE") == "1"

server = MCPServer(
    name="shiftnet",
    instructions=(
        "ShiftNet is a WordNet-style lexicon where every sense has a registration date and parent senses "
        "(the sense it grew from). Sense ids look like cloud.n.02. "
        "Sense discovery clusters a word's usages from the fineweb-edu web corpus; each cluster is a candidate "
        "sense with its strongest descriptive terms, crawl dates and typical usages. To review one: read it with "
        "get_candidate, compare it with the word's senses (get_word), then match it to an existing sense, promote "
        "it with a concise WordNet-style gloss and its parent sense, or reject it (noise, mixed senses, a proper "
        "name). Crawl dates start in 2013 and only show that a usage existed by then; never present them as the "
        "date a sense was born."
    ),
)

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
EDIT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)


def _json(obj: Any) -> Any:
    """Rows contain UUIDs, dates and timestamps; return plain JSON."""
    return json.loads(json.dumps(obj, default=str))


def _read(fn, *args):
    with db.connect() as conn:
        return _json(fn(conn, *args))


def _write(fn, *args):
    with db.transaction() as conn:
        return _json(fn(conn, *args))


# ---------- Lexicon ----------


@server.tool(annotations=READ)
def search_lexicon(query: str, limit: int = 8) -> list[dict]:
    """Head words and multi-word expressions matching a query (case and accent insensitive, from 2 letters).
    With no match, returns close spellings flagged close_spelling."""
    return _read(lexicon.search, query, limit)


@server.tool(annotations=READ)
def get_word(lemma: str) -> list[dict]:
    """All senses of a head word in registration order: gloss, date, shift type, parents, synonyms."""
    return _read(lexicon.word, lemma)


@server.tool(annotations=READ)
def get_sense(sense_id: str, attestations: int = 10) -> dict | None:
    """One sense (e.g. cloud.n.02) with its parents, children, relations and most relevant attestations."""
    return _read(lexicon.sense, sense_id, attestations)


# ---------- Discovery ----------


@server.tool(annotations=READ)
def list_candidates(lemma: str | None = None, status: str = "pending", limit: int = 50) -> list[dict]:
    """Candidate senses found by discovery runs. status: pending, matched, promoted, rejected or all."""
    from .discovery.store import list_candidates as fn

    return _read(fn, lemma, None if status == "all" else CandidateStatus(status), limit)


@server.tool(annotations=READ)
def get_candidate(candidate_id: str, usages: int = 10) -> dict | None:
    """A candidate sense: descriptive terms, crawl-date spread, the nearest existing sense and its score,
    the most typical usages and a few borderline ones."""
    from .discovery.store import get_candidate as fn

    return _read(fn, candidate_id, usages)


if WRITE:

    @server.tool(annotations=EDIT)
    def save_senses(senses: list[SenseIn]) -> list[str]:
        """Insert or update senses with parents, synonyms, relations and attestations, in one transaction.
        Omit id to create a sense (it gets the next id for its lemma and part of speech); give an existing id
        to update it (its parents, synonyms and relations are replaced). Returns the ids."""
        return _write(lexicon.save_senses, senses)

    @server.tool(annotations=EDIT)
    def add_attestation(sense_id: str, attestation: AttestationIn) -> str:
        """Quote a dated usage for a sense, citing its source (reused if already known)."""
        return _write(lexicon.add_attestation, sense_id, attestation)

    @server.tool(annotations=EDIT)
    def match_candidate(
        candidate_id: str, sense_id: str | None = None, attestations: int = 3, note: str | None = None
    ) -> dict:
        """Mark a candidate as an existing sense (default: its nearest sense) and quote its most typical
        usages as attestations of that sense."""
        from .discovery.store import match

        return _write(match, candidate_id, sense_id, attestations, note)

    @server.tool(annotations=EDIT)
    def promote_candidate(candidate_id: str, promotion: PromoteIn) -> dict:
        """Write a candidate to the lexicon as a new sense of its lemma, with the given part of speech, gloss
        and parent senses. It is dated by its first crawl year unless date_label / date_earliest are given."""
        from .discovery.store import promote

        return _write(promote, candidate_id, promotion)

    @server.tool(annotations=EDIT)
    def reject_candidate(candidate_id: str, note: str | None = None) -> dict:
        """Discard a candidate (noise, several senses mixed, proper names …)."""
        from .discovery.store import reject

        return _write(reject, candidate_id, note)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
    async def discover_senses(
        lemma: str,
        forms: list[str] | None = None,
        dumps: list[str] | None = None,
        per_dump: int = 100,
        threshold: float = 0.35,
        min_size: int = 5,
    ) -> dict:
        """Sample usages of a lemma from fineweb-edu snapshots, cluster them with LexSPLADE and store the
        clusters as pending candidates. Slow: streams the corpus and runs a 340M-parameter encoder
        (minutes on CPU for a few hundred usages)."""
        from .discovery.pipeline import discover
        from .discovery.store import save_run

        def run() -> dict:
            with db.connect() as conn:
                existing = lexicon.sense_texts(conn, lemma)
            result = discover(
                lemma, _encoder(), forms=forms, dumps=dumps, per_dump=per_dump, threshold=threshold,
                min_size=min_size, existing=existing,
            )
            with db.transaction() as conn:
                run_id = save_run(conn, result)
                candidates = _json(list_candidates_for(conn, run_id))
            return {"run_id": str(run_id), "usages": len(result.usages),
                    "unclustered": result.assignments.count(-1), "candidates": candidates}

        return await anyio.to_thread.run_sync(run)


def list_candidates_for(conn, run_id) -> list[dict]:
    return conn.execute(
        """select id, cluster, size, array(select t ->> 'term' from jsonb_array_elements(terms) t limit 8) as terms,
                  first_seen, nearest_sense_id, nearest_score
           from public.sense_candidates where run_id = %s order by cluster""",
        (run_id,),
    ).fetchall()


@lru_cache(maxsize=1)
def _encoder():
    from .discovery.encoder import Encoder

    return Encoder(os.environ.get("SHIFTNET_ENCODER", "jadermcs/lexsplade-bert-large-silver"))


def main() -> None:
    p = argparse.ArgumentParser(prog="shiftnet-mcp")
    p.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http"])
    a = p.parse_args()
    db.database_url()  # fail early without DATABASE_URL
    server.run(a.transport)


if __name__ == "__main__":
    main()
