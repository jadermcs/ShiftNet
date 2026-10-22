"""shiftnet: load lexicon data and run sense discovery from the command line.

  shiftnet import senses.jsonl                 commit senses (one SenseIn JSON per line, or a JSON list)
  shiftnet discover cloud --per-dump 200       sample, encode, cluster and store candidates
  shiftnet candidates [--lemma cloud]          list pending candidates
  shiftnet show <candidate-id>                 terms, dates and typical usages
  shiftnet match <candidate-id> [--sense id]   it is an existing sense
  shiftnet promote <candidate-id> --pos noun --gloss "…" [--parent cloud.n.02 --shift metaphor]
  shiftnet reject <candidate-id> [--note …]

All commands use DATABASE_URL (a privileged Postgres connection string).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import psycopg
from pydantic import TypeAdapter, ValidationError

from . import db, lexicon
from .models import CandidateStatus, PartOfSpeech, PromoteIn, SenseIn, ShiftType, ValidationMethod


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def cmd_import(a: argparse.Namespace) -> int:
    text = Path(a.file).read_text() if a.file != "-" else sys.stdin.read()
    stripped = text.lstrip()
    raw = json.loads(text) if stripped.startswith("[") else [json.loads(l) for l in text.splitlines() if l.strip()]
    try:
        senses = TypeAdapter(list[SenseIn]).validate_python(raw)
    except ValidationError as e:
        print(e, file=sys.stderr)
        return 1
    with db.transaction(a.database_url) as conn:
        ids = lexicon.save_senses(conn, senses)
        if a.dry_run:
            raise psycopg.Rollback()
    print(f"{'Checked' if a.dry_run else 'Saved'} {len(ids)} senses: {', '.join(ids)}")
    return 0


def cmd_discover(a: argparse.Namespace) -> int:
    from .discovery.encoder import Encoder
    from .discovery.pipeline import discover
    from .discovery.store import save_run

    data_files = None
    if a.data_files:
        # --data-files CC-MAIN-2013-20=/path/*.parquet (repeatable)
        data_files = {}
        for spec in a.data_files:
            dump, _, files = spec.partition("=")
            data_files[dump] = files
    with db.connect(a.database_url) as conn:
        existing = lexicon.sense_texts(conn, a.lemma)
    encoder = Encoder(a.model, device=a.device, batch_size=a.batch_size)
    result = discover(
        a.lemma, encoder, forms=a.forms, dumps=a.dumps, per_dump=a.per_dump, max_docs=a.max_docs,
        threshold=a.threshold, min_size=a.min_size, existing=existing, data_files=data_files,
    )
    with db.transaction(a.database_url) as conn:
        run_id = save_run(conn, result)
    noise = result.assignments.count(-1)
    print(f"Run {run_id}: {len(result.usages)} usages, {len(result.candidates)} candidates, {noise} unclustered")
    for c in result.candidates:
        near = f"  ~ {c.nearest_sense_id} ({c.nearest_score:.2f})" if c.nearest_sense_id else ""
        terms = ", ".join(t.term for t in c.terms[:8])
        print(f"  #{c.cluster:<2} {c.size:>4} usages  {c.first_seen or '?'}  {terms}{near}")
    return 0


def cmd_candidates(a: argparse.Namespace) -> int:
    from .discovery.store import list_candidates

    with db.connect(a.database_url) as conn:
        rows = list_candidates(conn, a.lemma, None if a.status == "all" else CandidateStatus(a.status), a.limit)
    for r in rows:
        near = f"  ~ {r['nearest_sense_id']} ({r['nearest_score']:.2f})" if r["nearest_sense_id"] else ""
        print(f"{r['id']}  {r['lemma']:<12} {r['status']:<8} {r['size']:>4}  {', '.join(r['terms'])}{near}")
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    from .discovery.store import get_candidate

    with db.connect(a.database_url) as conn:
        c = get_candidate(conn, a.candidate, a.usages)
    if c is None:
        print(f"No candidate {a.candidate}", file=sys.stderr)
        return 1
    _print(c)
    return 0


def _review(a: argparse.Namespace, fn) -> int:
    from .discovery.store import ReviewError

    try:
        with db.transaction(a.database_url) as conn:
            ref = fn(conn)
    except (ReviewError, ValidationError) as e:
        print(e, file=sys.stderr)
        return 1
    print(f"{ref.id}: {ref.status}" + (f" → {ref.sense_id}" if ref.sense_id else ""))
    return 0


def cmd_match(a):
    from .discovery.store import match

    return _review(a, lambda conn: match(conn, a.candidate, a.sense, a.attestations, a.note))


def cmd_promote(a):
    from .discovery.store import promote

    p = PromoteIn(
        pos=a.pos, gloss=a.gloss, parent_ids=a.parent or [], shift=a.shift, date_label=a.date_label,
        date_earliest=a.date_earliest, examples=a.examples, attestations=a.attestations,
        validation=a.validation, note=a.note,
    )
    return _review(a, lambda conn: promote(conn, a.candidate, p))


def cmd_reject(a):
    from .discovery.store import reject

    return _review(a, lambda conn: reject(conn, a.candidate, a.note))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shiftnet", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--database-url", help="defaults to $DATABASE_URL")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("import", help="commit senses from JSON / JSONL")
    s.add_argument("file", help="path, or - for stdin")
    s.add_argument("--dry-run", action="store_true", help="validate and write, then roll back")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("discover", help="discover candidate senses of a lemma in fineweb-edu")
    s.add_argument("lemma")
    s.add_argument("--forms", nargs="+", help="surface forms to search for (default: lemma and plural)")
    s.add_argument("--dumps", nargs="+", help="fineweb-edu snapshots (default: 8 from 2013 to 2025)")
    s.add_argument("--data-files", nargs="+", metavar="DUMP=GLOB", help="read local parquet instead of streaming")
    s.add_argument("--per-dump", type=int, default=200, help="usages per snapshot (default 200)")
    s.add_argument("--max-docs", type=int, default=200_000, help="documents scanned per snapshot at most")
    s.add_argument("--threshold", type=float, default=0.35, help="average cosine similarity to merge clusters")
    s.add_argument("--min-size", type=int, default=5, help="smaller clusters are left unclustered")
    s.add_argument("--model", default="jadermcs/lexsplade-bert-large-silver")
    s.add_argument("--device", help="cpu, cuda, mps (default: best available)")
    s.add_argument("--batch-size", type=int, default=32)
    s.set_defaults(fn=cmd_discover)

    s = sub.add_parser("candidates", help="list candidate senses")
    s.add_argument("--lemma")
    s.add_argument("--status", default="pending", choices=[*CandidateStatus, "all"])
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(fn=cmd_candidates)

    s = sub.add_parser("show", help="one candidate with its usages")
    s.add_argument("candidate")
    s.add_argument("--usages", type=int, default=10)
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("match", help="the candidate is an existing sense")
    s.add_argument("candidate")
    s.add_argument("--sense", help="sense id (default: the nearest sense)")
    s.add_argument("--attestations", type=int, default=3, help="typical usages to quote for the sense")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_match)

    s = sub.add_parser("promote", help="write the candidate as a new sense")
    s.add_argument("candidate")
    s.add_argument("--pos", required=True, choices=list(PartOfSpeech))
    s.add_argument("--gloss", required=True)
    s.add_argument("--parent", action="append", help="parent sense id (repeat for a merge)")
    s.add_argument("--shift", choices=list(ShiftType))
    s.add_argument("--date-label", help="as recorded (default: first crawl year)")
    s.add_argument("--date-earliest", type=int)
    s.add_argument("--examples", type=int, default=2)
    s.add_argument("--attestations", type=int, default=3)
    s.add_argument("--validation", default=ValidationMethod.automatic, choices=list(ValidationMethod))
    s.add_argument("--note")
    s.set_defaults(fn=cmd_promote)

    s = sub.add_parser("reject", help="discard the candidate")
    s.add_argument("candidate")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_reject)
    return p


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(message)s")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
