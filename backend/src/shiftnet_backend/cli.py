"""shiftnet: load lexicon data and run sense discovery from the command line.

  shiftnet serve [--static ../app/dist]        the local API the web app talks to (http://127.0.0.1:8000)
  shiftnet seed                                load the sample lexicon into an empty database
  shiftnet import senses.jsonl                 commit senses (one SenseIn JSON per line, or a JSON list)
  shiftnet discover cloud --per-dump 200       sample, encode, cluster and store candidates
  shiftnet candidates [--lemma cloud]          list pending candidates
  shiftnet show <candidate-id>                 terms, dates and typical usages
  shiftnet match <candidate-id> [--sense id]   it is an existing sense
  shiftnet promote <candidate-id> --pos noun --gloss "…" [--parent cloud.n.02 --shift metaphor]
  shiftnet reject <candidate-id> [--note …]
  shiftnet relations suggest [cloud mouse …]   propose WordNet relations with LexSPLADE (all senses if none given)
  shiftnet relations show cloud.n.02           the stored suggestions for a sense
  shiftnet bulk <stage> --workdir DIR          candidate senses for the N most frequent lemmas:
                                               download, count, vocab, sample, encode, cluster, import, status

All commands use the SQLite database at $SHIFTNET_DB (default ~/data/shiftnet.sqlite), or --db.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from . import db, lexicon
from .discovery.corpus import DEFAULT_DUMPS
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
    try:
        with db.transaction(a.db) as conn:
            ids = lexicon.save_senses(conn, senses)
            if a.dry_run:
                raise db.Rollback()
    except db.Rollback:
        pass
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
    with db.reader(a.db) as conn:
        existing = lexicon.sense_texts(conn, a.lemma)
    encoder = Encoder(a.model, device=a.device, batch_size=a.batch_size)
    result = discover(
        a.lemma, encoder, forms=a.forms, dumps=a.dumps, per_dump=a.per_dump, max_docs=a.max_docs,
        threshold=a.threshold, min_size=a.min_size, existing=existing, data_files=data_files,
    )
    with db.transaction(a.db) as conn:
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

    with db.reader(a.db) as conn:
        rows = list_candidates(conn, a.lemma, None if a.status == "all" else CandidateStatus(a.status), a.limit)
    for r in rows:
        near = f"  ~ {r['nearest_sense_id']} ({r['nearest_score']:.2f})" if r["nearest_sense_id"] else ""
        print(f"{r['id']}  {r['lemma']:<12} {r['status']:<8} {r['size']:>4}  {', '.join(r['terms'])}{near}")
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    from .discovery.store import get_candidate

    with db.reader(a.db) as conn:
        c = get_candidate(conn, a.candidate, a.usages)
    if c is None:
        print(f"No candidate {a.candidate}", file=sys.stderr)
        return 1
    _print(c)
    return 0


def _review(a: argparse.Namespace, fn) -> int:
    from .discovery.store import ReviewError

    try:
        with db.transaction(a.db) as conn:
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


def cmd_relations_suggest(a: argparse.Namespace) -> int:
    from .discovery.encoder import Encoder
    from .discovery.relation_store import save_suggestions, suggest
    from .discovery.relations import RelationSuggester

    suggester = RelationSuggester(Encoder(a.model, device=a.device, batch_size=a.batch_size), per_relation=a.per_relation)
    with db.transaction(a.db) as conn:
        found = suggest(conn, suggester, a.lemmas or None, min_score=a.min_score)
        covered = {
            r["id"] for r in conn.execute(
                "select id from senses where ? or lower(lemma) in (select value from json_each(?))",
                (not a.lemmas, [l.lower() for l in a.lemmas]),
            )
        }
        n = save_suggestions(conn, found, suggester.enc.name, covered)
    by_type: dict[str, int] = {}
    for x in found:
        by_type[x.type] = by_type.get(x.type, 0) + 1
    print(f"Stored {n} suggestions for {len(covered)} senses: " + ", ".join(f"{v} {k}" for k, v in sorted(by_type.items())))
    return 0


def cmd_relations_show(a: argparse.Namespace) -> int:
    from .discovery.relation_store import list_suggestions

    with db.reader(a.db) as conn:
        rows = list_suggestions(conn, a.sense)
    for r in rows:
        t = r["target_sense_id"] or r["target_synset_id"]
        target = f"  → {t}" if t else ""
        print(f"{r['type']:<9} {r['target_lemma']:<18} {r['score']:.2f}{target}")
    return 0


def cmd_bulk(a: argparse.Namespace) -> int:
    from .discovery import bulk

    w = Path(a.workdir)
    if a.stage == "download":
        bulk.download(w, a.dumps or DEFAULT_DUMPS, a.docs, Path(a.local) if a.local else None)
    elif a.stage == "count":
        bulk.count(w, workers=a.workers)
    elif a.stage == "vocab":
        v = bulk.build_vocab(w, top=a.top, min_count=a.min_count, max_capitalised=a.max_capitalised,
                             dictionary_only=a.dictionary_only)
        print(f"{len(v['lemmas'])} lemmas: {', '.join(e['lemma'] for e in v['lemmas'][:20])} …")
    elif a.stage == "sample":
        bulk.sample(w, per_lemma=a.per_lemma, tokenizer=a.model, seed=a.seed, workers=a.workers)
    elif a.stage == "encode":
        from .discovery.encoder import Encoder

        enc = Encoder(a.model, device=a.device, batch_size=a.batch_size, dtype=a.dtype)
        bulk.encode(w, enc, shard=a.shard, shards=a.shards, k=a.topk)
    elif a.stage == "cluster":
        bulk.cluster_all(w, threshold=a.threshold, min_size=a.min_size, min_usages=a.min_usages,
                         max_usages=a.max_usages, seed=a.seed, workers=a.workers)
    elif a.stage == "import":
        from .discovery.encoder import Encoder

        n = bulk.import_runs(
            lambda write: db.transaction(a.db) if write else db.reader(a.db),
            w, a.tag or w.resolve().name, lambda: Encoder(a.model, device=a.device, batch_size=a.batch_size),
        )
        print(f"Stored {n} runs")
    else:
        _print(bulk.describe(w))
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    from .api import serve

    if a.db:
        os.environ[db.ENV_VAR] = a.db
    serve(a.host, a.port, a.static)
    return 0


def cmd_seed(a: argparse.Namespace) -> int:
    with db.reader(a.db) as conn:
        db.seed(conn)
        n = conn.execute("select count(*) as n from senses").fetchone()["n"]
    print(f"Loaded the sample lexicon: {n} senses into {db.database_path(a.db)}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shiftnet", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", help="SQLite database file (default: $SHIFTNET_DB or ~/data/shiftnet.sqlite)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the local API the web app talks to")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--static", help="also serve this built app directory (app/dist) at /")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("seed", help="load the sample lexicon into an empty database")
    s.set_defaults(fn=cmd_seed)

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

    rel = sub.add_parser("relations", help="WordNet relation suggestions").add_subparsers(dest="rel_cmd", required=True)
    s = rel.add_parser("suggest", help="propose relations with LexSPLADE and store them")
    s.add_argument("lemmas", nargs="*", help="head words (default: every sense)")
    s.add_argument("--per-relation", type=int, default=6, help="suggestions per relation type and sense")
    s.add_argument("--min-score", type=float, default=0.2)
    s.add_argument("--model", default="jadermcs/lexsplade-bert-large-silver")
    s.add_argument("--device")
    s.add_argument("--batch-size", type=int, default=32)
    s.set_defaults(fn=cmd_relations_suggest)
    s = rel.add_parser("show", help="stored suggestions for a sense")
    s.add_argument("sense")
    s.set_defaults(fn=cmd_relations_show)

    s = sub.add_parser("bulk", help="candidate senses for the N most frequent lemmas of fineweb-edu, in stages")
    s.add_argument("stage", choices=["download", "count", "vocab", "sample", "encode", "cluster", "import", "status"])
    s.add_argument("--workdir", required=True, help="where every stage reads and writes")
    s.add_argument("--workers", type=int, default=os.cpu_count(), help="processes for count, sample, cluster")
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--dumps", nargs="+", help="download: snapshots (default: 8 from 2013 to 2025)")
    s.add_argument("--docs", type=int, default=500_000, help="download: documents per snapshot (default 500k)")
    s.add_argument("--local", help="download: a local mirror holding data/<dump>/*.parquet instead of the Hub")
    s.add_argument("--top", type=int, default=20_000, help="vocab: lemmas to keep (default 20k)")
    s.add_argument("--min-count", type=int, default=20, help="vocab: forms seen fewer times are ignored")
    s.add_argument("--max-capitalised", type=float, default=0.5, help="vocab: share above which a lemma is a name")
    s.add_argument("--dictionary-only", action="store_true", help="vocab: only WordNet lemmas (no neologisms)")
    s.add_argument("--per-lemma", type=int, default=2000, help="sample: usages per lemma, spread over the snapshots")
    s.add_argument("--model", default="jadermcs/lexsplade-bert-large-silver")
    s.add_argument("--device", help="encode/import: cuda, cuda:1, cpu …")
    s.add_argument("--dtype", choices=["bfloat16", "float16", "float32"], help="encode: bfloat16 on a GPU")
    s.add_argument("--batch-size", type=int, default=256)
    s.add_argument("--topk", type=int, default=128, help="encode: dimensions kept per vector")
    s.add_argument("--shard", type=int, default=0, help="encode: this process's shard (one per GPU)")
    s.add_argument("--shards", type=int, default=1)
    s.add_argument("--threshold", type=float, default=0.35, help="cluster: average cosine similarity to merge")
    s.add_argument("--min-size", type=int, default=10, help="cluster: smaller clusters are left unclustered")
    s.add_argument("--min-usages", type=int, default=50, help="cluster: lemmas with fewer usages are skipped")
    s.add_argument("--max-usages", type=int, default=2500, help="cluster: at most this many usages per lemma")
    s.add_argument("--tag", help="import: run label stored as params.bulk (default: the workdir's name)")
    s.set_defaults(fn=cmd_bulk)

    s = sub.add_parser("reject", help="discard the candidate")
    s.add_argument("candidate")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_reject)
    return p


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(message)s")
    for noisy in ("httpx", "httpcore", "huggingface_hub", "datasets", "urllib3", "fsspec"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
