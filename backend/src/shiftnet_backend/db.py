"""The ShiftNet database: one SQLite file.

The path comes from SHIFTNET_DB (default ~/data/shiftnet.sqlite). Every connection made here registers
the SQL functions the schema and queries use (normalize_lemma, levenshtein, similarity), turns on
foreign keys and WAL, and returns rows as dicts with JSON columns decoded.

Postgres did two things with triggers that are plain functions here, called by every writer:
renumber_senses() (sense_num and branch, in registration order) and refresh_relevance() (the score that
orders attestations).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import unicodedata
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

ENV_VAR = "SHIFTNET_DB"
DEFAULT_PATH = Path.home() / "data" / "shiftnet.sqlite"
SCHEMA = Path(__file__).with_name("schema.sql")
SEED = Path(__file__).resolve().parents[2] / "seed" / "seed.sql"

# ---------- Types ----------

sqlite3.register_adapter(list, lambda v: json.dumps(v, ensure_ascii=False))
sqlite3.register_adapter(tuple, lambda v: json.dumps(list(v), ensure_ascii=False))
sqlite3.register_adapter(dict, lambda v: json.dumps(v, ensure_ascii=False))
sqlite3.register_adapter(uuid.UUID, str)
sqlite3.register_adapter(dt.date, lambda v: v.isoformat())
sqlite3.register_adapter(dt.datetime, lambda v: v.isoformat())
sqlite3.register_converter("JSON", lambda b: json.loads(b))
sqlite3.register_converter("DATE", lambda b: dt.date.fromisoformat(b.decode()[:10]))
sqlite3.register_converter("TIMESTAMP", lambda b: b.decode())  # ISO 8601 text, as the app expects


def _dict_row(cur: sqlite3.Cursor, row: tuple) -> dict:
    return {d[0]: v for d, v in zip(cur.description, row)}


# ---------- SQL functions ----------

_LIGATURES = str.maketrans({"æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ß": "ss", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
                            "ł": "l", "Ł": "L", "þ": "th", "Þ": "TH", "ð": "d", "Ð": "D", "’": "'", "‘": "'"})


@lru_cache(maxsize=65536)
def normalize_lemma(t: str | None) -> str | None:
    """Case- and accent-insensitive key used by search: lower(trim(unaccent(t)))."""
    if t is None:
        return None
    s = unicodedata.normalize("NFKD", t.translate(_LIGATURES))
    return "".join(c for c in s if not unicodedata.combining(c)).strip().lower()


def levenshtein(a: str | None, b: str | None) -> int | None:
    if a is None or b is None:
        return None
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _trigrams(t: str) -> set[str]:
    out: set[str] = set()
    for w in re.findall(r"\w+", t.lower()):
        p = f"  {w} "
        out.update(p[i : i + 3] for i in range(len(p) - 2))
    return out


def similarity(a: str | None, b: str | None) -> float | None:
    """pg_trgm's similarity(): shared trigrams over all trigrams of the two strings."""
    if a is None or b is None:
        return None
    x, y = _trigrams(a), _trigrams(b)
    return len(x & y) / len(x | y) if x | y else 0.0


def text_key(t: str | None) -> str:
    """Key for comparing quotes and glosses: letters and digits only, lower case, no accents."""
    return normalize_lemma(re.sub(r"[\W_]+", " ", t or "")) or ""


def period_label(y: int) -> str:
    """Period used for the timeline's separators and the stats: Old English, centuries, decades from 1900."""
    if y < 1100:
        return "Old English"
    if y >= 1900:
        return f"{y // 10 * 10}s"
    c = y // 100 + 1
    suffix = "th" if c % 100 in (11, 12, 13) else {1: "st", 2: "nd", 3: "rd"}.get(c % 10, "th")
    return f"{c}{suffix} century"


POS_ORDER = ("noun", "verb", "adjective", "adverb")
SHIFT_ORDER = ("root", "broadening", "narrowing", "metaphor", "metonymy", "amelioration", "pejoration", "other")


def _register(conn: sqlite3.Connection) -> None:
    conn.create_function("normalize_lemma", 1, normalize_lemma, deterministic=True)
    conn.create_function("text_key", 1, text_key, deterministic=True)
    conn.create_function("levenshtein", 2, levenshtein, deterministic=True)
    conn.create_function("similarity", 2, similarity, deterministic=True)
    conn.create_function("period_label", 1, period_label, deterministic=True)
    conn.create_function("pos_order", 1, lambda p: POS_ORDER.index(p) if p in POS_ORDER else 99, deterministic=True)
    conn.create_function("shift_order", 1, lambda s: SHIFT_ORDER.index(s) if s in SHIFT_ORDER else 99, deterministic=True)
    conn.create_function("uuid4", 0, lambda: str(uuid.uuid4()))


# ---------- Connections ----------


def database_path(path: str | os.PathLike | None = None) -> Path:
    return Path(path or os.environ.get(ENV_VAR) or DEFAULT_PATH).expanduser()


def connect(path: str | os.PathLike | None = None, *, create: bool = True) -> sqlite3.Connection:
    """A connection in autocommit mode; use transaction() for writes. Creates the database (and its
    schema) if it does not exist yet, unless create is False."""
    p = database_path(path)
    if not p.exists():
        if not create:
            raise FileNotFoundError(f"No ShiftNet database at {p} (set {ENV_VAR})")
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        p, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES, isolation_level=None,
        check_same_thread=False, timeout=30,
    )
    conn.row_factory = _dict_row
    _register(conn)
    conn.execute("pragma foreign_keys = on")
    conn.execute("pragma journal_mode = wal")
    conn.execute("pragma synchronous = normal")
    conn.execute("pragma busy_timeout = 30000")
    init(conn)  # every statement is "if not exists": creates a new database, and adds what a newer schema has
    return conn


@contextmanager
def reader(path: str | os.PathLike | None = None) -> Iterator[sqlite3.Connection]:
    """A connection for reading, closed afterwards."""
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text())


def seed(conn: sqlite3.Connection, path: str | os.PathLike = SEED) -> None:
    """Load the sample lexicon (seed/seed.sql) into an empty database."""
    if conn.execute("select 1 from senses limit 1").fetchone():
        raise RuntimeError("The database already has senses; seed an empty one")
    conn.executescript("begin;\n" + Path(path).read_text() + "\ncommit;")
    with transaction(conn):
        renumber_senses(conn)
        refresh_relevance(conn)


@contextmanager
def transaction(path: str | os.PathLike | sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
    """A connection (or the one given) whose work is committed on success and rolled back on any error.
    BEGIN IMMEDIATE takes the write lock up front, so concurrent writers wait instead of failing."""
    own = not isinstance(path, sqlite3.Connection)
    conn = connect(path) if own else path
    try:
        if conn.in_transaction:  # nested: a savepoint
            name = f"sp_{uuid.uuid4().hex[:8]}"
            conn.execute(f"savepoint {name}")
            try:
                yield conn
            except BaseException:
                conn.execute(f"rollback to {name}")
                conn.execute(f"release {name}")
                raise
            conn.execute(f"release {name}")
        else:
            conn.execute("begin immediate")
            try:
                yield conn
            except BaseException:
                conn.execute("rollback")
                raise
            conn.execute("commit")
    finally:
        if own:
            conn.close()


class Rollback(Exception):
    """Raise inside transaction() to discard its work without an error reaching the caller's caller."""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def placeholders(values: Iterable) -> str:
    return ", ".join("?" for _ in values)


# ---------- What Postgres did with triggers ----------


def renumber_senses(conn: sqlite3.Connection) -> None:
    """Keep sense_num (n. 1, n. 2 … per lemma and pos) and branch (0–7 per lemma) in registration order."""
    conn.execute(
        """update senses set sense_num = r.sense_num, branch = r.branch
           from (
             select id,
               row_number() over (partition by lemma, pos order by date_earliest, id) as sense_num,
               (row_number() over (partition by lemma order by date_earliest, id) - 1) % 8 as branch
             from senses
           ) r
           where senses.id = r.id and (senses.sense_num is not r.sense_num or senses.branch is not r.branch)"""
    )


# Relevance used to pick the quotations shown first (word pages show the top 3). Rewards a quote that
# contains the head word, a checked row, a citable kind of source, a known date, a readable length and
# early evidence (within 50 years of the sense's registration). relevance_override replaces it.
_RELEVANCE = """
  update attestations set relevance = coalesce(attestations.relevance_override, round(
      (case when instr(normalize_lemma(attestations.quote), normalize_lemma(s.lemma)) > 0 then 0.3 else 0 end)
    + (case attestations.validation when 'automatic' then 0.1 else 0.2 end)
    + (case src.kind
         when 'book' then 0.15 when 'journal' then 0.15 when 'dictionary' then 0.15
         when 'article' then 0.1 when 'newspaper' then 0.1 when 'corpus' then 0.1 when 'archive' then 0.1
         when 'website' then 0.07
         else 0.05
       end)
    + (case when attestations.year is not null then 0.1 else 0 end)
    + (case when length(attestations.quote) between 40 and 200 then 0.15
            when length(attestations.quote) between 20 and 300 then 0.1 else 0.05 end)
    + (case when attestations.year between s.date_earliest and s.date_earliest + 50 then 0.1 else 0 end), 4))
  from senses s, sources src
  where s.id = attestations.sense_id and src.id = attestations.source_id"""


def refresh_relevance(conn: sqlite3.Connection, ids: Iterable[str] | None = None) -> None:
    """Recompute attestation relevance, for the given attestation ids or all of them."""
    if ids is None:
        conn.execute(_RELEVANCE)
        return
    ids = [str(i) for i in ids]
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        conn.execute(f"{_RELEVANCE} and attestations.id in ({placeholders(chunk)})", chunk)
