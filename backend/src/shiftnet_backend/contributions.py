"""Contributions: proposed usages (attestations of an existing sense), senses and relations.

A port of the Supabase contribution flow to the local, single-user setup: the one local user is
both contributor and moderator. Each submission runs the automatic checks. Each check yields one of
  error   the submission is refused and nothing is stored (missing field, bad URL, duplicate …)
  review  stored as pending, to be accepted or rejected in the review queue (antedating …)
  note    shown, no effect on the outcome
  pass    recorded so the interface can show what was checked
A submission with no error and no review flag is published at once with validation 'automatic'; one
accepted in the review queue is published with validation 'manual'. An auto-accepted contribution
can later be confirmed (automatic → manual) or withdrawn.

The multi-user rules of the hosted version are gone: rate limits, the "trusted contributor" rule and
"another moderator must review your own contributions".
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from typing import Any

from . import db
from .lexicon import next_sense_id, source_for

LOCAL_USER = "local"

POS = ("noun", "verb", "adjective", "adverb")
SHIFTS = ("root", "broadening", "narrowing", "metaphor", "metonymy", "amelioration", "pejoration", "other")
SOURCE_TYPES = ("dictionary", "corpus", "citation")
REFERENCE_KINDS = ("book", "website", "article", "journal", "newspaper", "dictionary", "corpus", "archive", "other")
RELATION_TYPES = ("synonym", "hypernym", "hyponym", "meronym", "holonym", "antonym", "derived")

Checks = list[dict[str, str]]


class ContributionError(Exception):
    """A request that cannot be carried out. status is the HTTP status the API answers with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class ChecksFailed(ContributionError):
    """The automatic checks refused the submission; carries the failed checks."""

    def __init__(self, checks: Checks):
        super().__init__("The contribution did not pass the automatic checks", 422)
        self.checks = [c for c in checks if c["level"] == "error"]


# ---------- Small helpers ----------


def clean(t: Any) -> str | None:
    """Trim, turn control characters into spaces, collapse whitespace; '' becomes None."""
    if t is None:
        return None
    t = _text(t)
    t = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", t)).strip()
    return t or None


def _text(v: Any) -> str:
    """A JSON value as text, the way Postgres' #>> '{}' prints it."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    return json.dumps(v)


def to_int(t: Any) -> int | None:
    if t is None:
        return None
    t = _text(t).strip()
    return int(t) if re.fullmatch(r"[+-]?\d{1,9}", t) else None


def to_date(t: Any) -> dt.date | None:
    if t is None:
        return None
    try:
        return dt.date.fromisoformat(_text(t).strip())
    except ValueError:
        return None


def clean_int(v: Any) -> int | str | None:
    """A whole number; a value that is not one is kept as a string so the checks can report it."""
    if clean(v) is None:
        return None
    n = to_int(v)
    return n if n is not None else _text(v)


def clean_date(v: Any) -> str | None:
    if clean(v) is None:
        return None
    d = to_date(v)
    return d.isoformat() if d else "invalid:" + _text(v)


def _strip_nulls(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def text_key(t: str | None) -> str:
    return db.text_key(t)


def norm(t: str | None) -> str | None:
    return db.normalize_lemma(t)


def rule(code: str, ok: bool | None, fail_level: str, pass_msg: str | None, fail_msg: str) -> Checks:
    """One check result, as a 0- or 1-element list. A None condition counts as failed; a None pass
    message records nothing on success."""
    if ok and pass_msg is None:
        return []
    if ok:
        return [{"code": code, "level": "pass", "message": pass_msg}]
    return [{"code": code, "level": fail_level, "message": fail_msg}]


def has_level(checks: Checks, level: str) -> bool:
    return any(c["level"] == level for c in checks)


def _between(v: Any, lo: Any, hi: Any) -> bool:
    return v is not None and lo <= v <= hi


def _len(v: str | None) -> int:
    return len(v) if v is not None else 0


def _int(v: Any) -> int | None:
    """The value when the cleaned payload holds a JSON number there."""
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def mentions(quote: str, forms: list[str]) -> bool:
    """Does the quote contain one of the forms, or a plausible inflection (clouds, clouded, nicer, trolling)?
    Prefix match at a word start; a final -e or -y is dropped from longer forms (nice → nicer, nicest)."""
    q = norm(quote) or ""
    for f in forms:
        n = norm(f) or ""
        stem = n[:-1] if len(n) > 3 and n[-1] in "ey" else n
        if stem and re.search(r"(?<!\w)(?=\w)" + re.escape(stem), q):
            return True
    return False


def isbn_ok(t: str | None) -> bool | None:
    """ISBN-10 / ISBN-13 checksum. None when the text does not look like an ISBN at all."""
    if t is None:
        return None
    d = re.sub(r"[- ]", "", re.sub(r"^\s*isbn(-1[03])?:?", "", t, count=1, flags=re.I)).upper()
    if re.fullmatch(r"[0-9]{9}[0-9X]", d):
        return sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(d)) % 11 == 0
    if re.fullmatch(r"[0-9]{13}", d):
        return d.startswith(("978", "979")) and sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d)) % 10 == 0
    return None


# ---------- Normalising a proposal ----------


def clean_source(s: dict) -> dict:
    return _strip_nulls({
        "kind": clean(s.get("kind")),
        "title": clean(s.get("title")),
        "author": clean(s.get("author")),
        "publisher": clean(s.get("publisher")),
        "published_label": clean(s.get("published_label")),
        "published_year": clean_int(s.get("published_year")),
        "url": clean(s.get("url")),
        "identifier": clean(s.get("identifier")),
        "accessed_on": clean_date(s.get("accessed_on")),
    })


def clean_usage(u: Any) -> dict | None:
    """Only known keys survive; the stored payload is this, never the raw client JSON."""
    if not isinstance(u, dict):
        return None
    return _strip_nulls({
        "sense_id": clean(u.get("sense_id")),
        "quote": clean(u.get("quote")),
        "year": clean_int(u.get("year")),
        "date_label": clean(u.get("date_label")),
        "locator": clean(u.get("locator")),
        "source": clean_source(u["source"] if isinstance(u.get("source"), dict) else {}),
    })


def clean_list(a: Any) -> list[str]:
    seen: dict[str, None] = {}
    for e in a if isinstance(a, list) else []:
        x = clean(e)
        if x is not None:
            seen.setdefault(x)
    return list(seen)


def clean_sense(conn: sqlite3.Connection, p: dict) -> dict:
    """An existing head word keeps its spelling ("Cloud" → "cloud")."""
    lemma = clean(p.get("lemma"))
    if lemma is not None:
        row = conn.execute("select lemma from senses where lemma_key = ? order by lemma limit 1", (norm(lemma),)).fetchone()
        lemma = row["lemma"] if row else lemma
    return _strip_nulls({
        "lemma": lemma,
        "pos": clean(p.get("pos")),
        "gloss": clean(p.get("gloss")),
        "examples": clean_list(p.get("examples")),
        "date_label": clean(p.get("date_label")),
        "date_earliest": clean_int(p.get("date_earliest")),
        "shift": clean(p.get("shift")),
        "date_source": clean(p.get("date_source")),
        "source_type": clean(p.get("source_type")),
        "parents": clean_list(p.get("parents")),
        "usage": clean_usage(p.get("usage")),
    })


def clean_relation(p: dict) -> dict:
    target_sense = clean(p.get("target_sense_id"))
    t = clean(p.get("type"))
    return _strip_nulls({
        "sense_id": clean(p.get("sense_id")),
        "type": t.lower() if t else None,
        "target_lemma": clean(p.get("target_lemma")),
        "target_sense_id": target_sense,
        "target_synset_id": clean(p.get("target_synset_id")) if target_sense is None else None,
        "note": clean(p.get("note")),
    })


# ---------- Automatic checks ----------

_URL = re.compile(r"^https?://[^\s/?#@:]+(\.[^\s/?#@:]+)+(:[0-9]{1,5})?([/?#]\S*)?$", re.I)
_DOI_START = re.compile(r"^(doi:\s*|https?://(dx\.)?doi\.org/)?10\.", re.I)
_DOI = re.compile(r"^(doi:\s*|https?://(dx\.)?doi\.org/)?10\.[0-9]{4,9}/\S+$", re.I)
_WORD = re.compile(r"^[^\W\d_](?:[^\W_]|[ '’.-]){0,59}$")
_RELATED_WORD = re.compile(r"^[^\W\d_](?:[^\W_]|[ '’.-])*$")
_MARKUP = re.compile(r"(<[a-z/!][^>]*>|https?://|www\.)", re.I)


def _this_year() -> int:
    return dt.date.today().year


def source_checks(s: dict, use_year: int | None) -> Checks:
    """The cited work."""
    now_y = _this_year()
    url, ident = s.get("url"), s.get("identifier")
    pub = _int(s.get("published_year"))
    acc = to_date(s.get("accessed_on"))
    isbn = isbn_ok(ident)
    c = (
        rule("reference_kind", s.get("kind") in REFERENCE_KINDS, "error",
             None, "Reference: choose what kind of work it is (book, website, article …)")
        + rule("reference_title", _between(_len(s.get("title")), 1, 300) and s.get("title") is not None, "error",
               None, "Reference: a title of at most 300 characters is required")
        + rule("reference_lengths",
               _len(s.get("author")) <= 200 and _len(s.get("publisher")) <= 200
               and _len(s.get("published_label")) <= 40 and _len(ident) <= 100,
               "error", None, "Reference: author and publisher at most 200 characters, date 40, identifier 100")
    )
    if "published_year" in s:
        c += rule("reference_year", _between(pub, 600, now_y), "error",
                  None, f"Reference: the publication year must be a whole year between 600 and {now_y}")
    if url is not None:
        c += rule("url_format", len(url) <= 2000 and bool(_URL.match(url)), "error",
                  "URL is a well-formed http(s) address", "Reference: the URL must be a full http:// or https:// address")
    if s.get("kind") == "website":
        c += rule("website_url", url is not None, "error", None, "Reference: a website needs its URL")
        c += rule("accessed_on", acc is not None, "note", None, "Add the date you accessed the page; websites change")
    if "accessed_on" in s:
        c += rule("accessed_on_valid", _between(acc, dt.date(1990, 1, 1), dt.date.today()), "error",
                  None, "Reference: the access date must be a real date, not in the future")
    if isbn is not None:
        c += rule("isbn", isbn, "review", "ISBN checksum is valid", "The ISBN checksum does not match; a moderator will check it")
    elif ident is not None and _DOI_START.match(ident):
        c += rule("doi", bool(_DOI.match(ident)), "review",
                  "DOI is well formed", "The DOI does not look well formed; a moderator will check it")
    c += rule("verifiable", url is not None or ident is not None, "review",
              "Reference has a URL or identifier",
              "No URL or identifier (ISBN, DOI, shelfmark): a moderator will check the reference")
    if pub is not None and use_year is not None:
        c += rule("published_after_use", use_year <= pub, "review",
                  None, f"The use ({use_year}) is dated after the work was published ({pub}); a moderator will check the dates")
    return c


def quote_checks(
    conn: sqlite3.Connection, u: dict, lemma: str | None, forms: list[str], registered: int | None,
    obsolete: int | None, sense_id: str | None, exclude: str | None,
) -> Checks:
    """A quotation, for an existing sense (sense_id) or for a proposed one (sense_id None).
    exclude skips the contribution being re-checked in the duplicate test."""
    now_y = _this_year()
    q = u.get("quote")
    y = _int(u.get("year"))
    c = (
        rule("quote_length", _between(_len(q), 15, 1200) and q is not None, "error",
             None, "Quote: one or two full sentences, 15 to 1,200 characters")
        + rule("year", _between(y, 600, now_y), "error", None, f"Year of use: a whole year between 600 and {now_y}")
        + rule("label_lengths", _len(u.get("date_label")) <= 40 and _len(u.get("locator")) <= 80, "error",
               None, "Date as recorded: at most 40 characters; page or locator: at most 80")
    )
    if q is None:
        return c
    if sense_id is not None:
        key = text_key(q)
        dup = conn.execute(
            "select 1 from attestations where sense_id = ? and text_key(quote) = ? limit 1", (sense_id, key)
        ).fetchone() or conn.execute(
            """select 1 from contributions
               where kind = 'usage' and status <> 'rejected' and sense_id = ? and id is not ?
                 and text_key(payload ->> 'quote') = ? limit 1""",
            (sense_id, exclude, key),
        ).fetchone()
        c += rule("duplicate_quote", not dup, "error",
                  "Quote is new for this sense", "This quote is already attested, or already proposed, for this sense")
    c += (
        rule("mentions_lemma", mentions(q, forms), "review",
             f"Quote contains “{lemma}” or a form of it",
             f"The quote does not contain “{lemma}” or a recognisable form of it; a moderator will check it")
        + rule("plain_text", not _MARKUP.search(q), "review", None, "The quote contains markup or a link; a moderator will check it")
    )
    if y is not None and registered is not None:
        c += rule("antedating", y >= registered, "review",
                  f"Year is not before the sense is registered ({registered})",
                  f"{y} is earlier than the date the sense is registered from ({registered}): a possible antedating, checked by a moderator")
    if y is not None and obsolete is not None:
        c += rule("after_obsolete", y <= obsolete, "review",
                  None, f"The sense is recorded as obsolete by {obsolete}; a moderator will check this later use")
    return c


def usage_report(conn: sqlite3.Connection, u: dict | None, exclude: str | None = None) -> Checks:
    """Everything checked for a proposed usage."""
    u = u or {}
    s = conn.execute("select * from senses where id = ?", (u.get("sense_id"),)).fetchone()
    if s is None:
        return rule("sense_exists", False, "error", None, "Choose an existing sense to attest")
    forms = [r["lemma"] for r in conn.execute("select lemma from sense_lemmas where sense_id = ?", (s["id"],))] + [s["lemma"]]
    return (
        quote_checks(conn, u, s["lemma"], forms, s["date_earliest"], s["obsolete_year"], s["id"], exclude)
        + source_checks(u.get("source") or {}, _int(u.get("year")))
    )


def sense_report(conn: sqlite3.Connection, p: dict, exclude: str | None = None) -> Checks:
    """Everything checked for a proposed sense."""
    now_y = _this_year()
    lemma, gloss, pos, shift = p.get("lemma"), p.get("gloss"), p.get("pos"), p.get("shift")
    year = _int(p.get("date_earliest"))
    parents = list(p.get("parents") or [])
    examples = p.get("examples") or []
    u = p.get("usage")
    c = (
        rule("lemma", lemma is not None and bool(_WORD.match(lemma)), "error",
             None, "Word: up to 60 letters, spaces, hyphens or apostrophes")
        + rule("pos", pos in POS, "error", None, "Part of speech: noun, verb, adjective or adverb")
        + rule("shift", shift in SHIFTS, "error", None, "Shift type: choose one")
        + rule("source_type", p.get("source_type") in SOURCE_TYPES, "error", None, "Date source type: dictionary, corpus or citation")
        + rule("gloss_length", gloss is not None and _between(len(gloss), 10, 300), "error",
               None, "Gloss: a definition of 10 to 300 characters")
        + rule("examples", len(examples) <= 5 and not any(len(e) > 200 for e in examples), "error",
               None, "Examples: at most 5, each up to 200 characters")
        + rule("date_label", p.get("date_label") is not None and _between(len(p["date_label"]), 1, 40), "error",
               None, "Date as recorded: required, at most 40 characters (e.g. 1965, c. 1300, 16th c.)")
        + rule("date_earliest", _between(year, 600, now_y), "error", None, f"Earliest year: a whole year between 600 and {now_y}")
        + rule("date_source", p.get("date_source") is not None and _between(len(p["date_source"]), 3, 300), "error",
               None, "Date source: say where the date comes from (3 to 300 characters)")
        + rule("parents_count", len(parents) <= 4, "error", None, "Parent senses: at most 4")
    )

    found = {r["id"]: r for r in conn.execute(
        f"select id, lemma, lemma_key, date_earliest from senses where id in ({db.placeholders(parents)})", parents
    )} if parents else {}
    missing = [x for x in parents if x not in found]
    c += rule("parents_exist", not missing, "error",
              "Parent senses exist" if parents else None, f"Unknown parent sense: {', '.join(missing)}")
    if shift == "root":
        c += rule("root_parents", not parents, "error", None, "A root sense has no parent senses; choose a shift type instead")
    elif shift is not None:
        c += rule("root_parents", bool(parents), "error", None,
                  "Choose the parent sense this one grew from, or mark it as a root sense")
    if not missing and year is not None and parents:
        c += rule("parents_older", not any(found[x]["date_earliest"] > year for x in parents), "review",
                  "Parent senses are older than the proposed date",
                  "A parent sense is registered after the proposed date; a moderator will check the lineage")
        c += rule("parents_same_word", not any(found[x]["lemma_key"] != norm(lemma) for x in parents), "note",
                  None, "A parent sense belongs to another word")

    if lemma is not None and pos in POS and gloss is not None:
        key, gkey = norm(lemma), text_key(gloss)
        same = conn.execute("select id, gloss from senses where lemma_key = ? and pos = ?", (key, pos)).fetchall()
        dup = any(text_key(s["gloss"]) == gkey for s in same) or conn.execute(
            """select 1 from contributions
               where kind = 'sense' and status = 'pending' and id is not ?
                 and normalize_lemma(lemma) = ? and payload ->> 'pos' = ? and text_key(payload ->> 'gloss') = ? limit 1""",
            (exclude, key, pos, gkey),
        ).fetchone()
        c += rule("duplicate_gloss", not dup, "error", None, "This gloss already exists, or is already proposed, for this word")
        near = max(((s["id"], db.similarity(text_key(s["gloss"]), gkey)) for s in same), key=lambda x: x[1], default=None)
        c += rule("similar_gloss", near is None or near[1] < 0.5, "review",
                  "Gloss differs from the existing senses",
                  f"The gloss is close to {near[0] if near else ''}; a moderator will check it is a new sense")
        c += rule("known_word", bool(conn.execute("select 1 from senses where lemma_key = ? limit 1", (key,)).fetchone()), "review",
                  None, f"“{lemma}” is a new head word; a moderator will check it")

    if isinstance(u, dict):
        c += quote_checks(conn, u, lemma, [lemma] if lemma else [], year, None, None, exclude)
        c += source_checks(u.get("source") or {}, _int(u.get("year")))
    else:
        c += rule("supporting_usage", False, "review", None,
                  "No supporting usage: a moderator will check the sense against its date source")
    return c


def relation_edge(conn: sqlite3.Connection, p: dict) -> dict | None:
    """The taxonomy edge a hypernym / hyponym proposal implies: {child, parent} synsets, or None when
    either side is not placed in the taxonomy."""
    if p.get("type") not in ("hypernym", "hyponym"):
        return None
    s = conn.execute("select synset_id from senses where id = ?", (p.get("sense_id"),)).fetchone()
    if s is None:
        return None
    t = conn.execute("select synset_id from senses where id = ?", (p.get("target_sense_id"),)).fetchone()
    target = (t["synset_id"] if t else None) or p.get("target_synset_id")
    child, parent = (s["synset_id"], target) if p["type"] == "hypernym" else (target, s["synset_id"])
    return {"child": child, "parent": parent} if child and parent else None


def synset_above(conn: sqlite3.Connection, child: str, ancestor: str) -> bool:
    """Is `ancestor` on some hypernym path above `child` (or the same synset)?"""
    seen, frontier = {child}, [child]
    while frontier and len(seen) < 10_000:
        if ancestor in frontier:
            return True
        rows = conn.execute(
            f"select hypernym_id from synset_hypernyms where synset_id in ({db.placeholders(frontier)})", frontier
        ).fetchall()
        frontier = [r["hypernym_id"] for r in rows if r["hypernym_id"] not in seen]
        seen.update(frontier)
    return ancestor in seen


def _suggestion_score(conn: sqlite3.Connection, sense_id: str, ty: str, t: str) -> float | None:
    row = conn.execute(
        "select score from relation_suggestions where sense_id = ? and type = ? and target_key = ?", (sense_id, ty, norm(t))
    ).fetchone()
    return row["score"] if row else None


def relation_report(conn: sqlite3.Connection, p: dict, exclude: str | None = None) -> Checks:
    """Everything checked for a proposed relation."""
    s = conn.execute("select * from senses where id = ?", (p.get("sense_id"),)).fetchone()
    if s is None:
        return rule("sense_exists", False, "error", None, "Choose an existing sense")
    ty, t = p.get("type"), p.get("target_lemma")
    c = (
        rule("relation_type", ty in RELATION_TYPES, "error", None,
             "Choose a relation: synonym, hypernym, hyponym, meronym, holonym, antonym or derived form")
        + rule("target_given", t is not None, "error", None, "Give the related word")
    )
    if t is not None:
        key = norm(t)
        c += rule("target_form", len(t) <= 60 and bool(_RELATED_WORD.match(t)), "error", None,
                  "The related word: letters, spaces, hyphens and apostrophes, at most 60 characters")
        c += rule("not_self", key != s["lemma_key"], "error", None, "A word cannot be related to itself")
        dup = (
            conn.execute("select 1 from relations where sense_id = ? and type = ? and normalize_lemma(target_lemma) = ?",
                         (s["id"], ty, key)).fetchone()
            or (ty == "synonym" and conn.execute(
                "select 1 from sense_lemmas where sense_id = ? and lemma_key = ?", (s["id"], key)).fetchone())
            or conn.execute(
                """select 1 from contributions
                   where kind = 'relation' and status = 'pending' and id is not ? and sense_id = ?
                     and payload ->> 'type' = ? and normalize_lemma(payload ->> 'target_lemma') = ?""",
                (exclude, s["id"], ty, key)).fetchone()
        )
        c += rule("not_duplicate", not dup, "error", None, "This relation is already recorded, or already proposed, for this sense")
        known = (
            conn.execute("select 1 from senses where lemma_key = ? limit 1", (key,)).fetchone()
            or conn.execute("select 1 from sense_lemmas where lemma_key = ? limit 1", (key,)).fetchone()
            or conn.execute("select 1 from synsets y, json_each(y.lemmas) m where normalize_lemma(m.value) = ? limit 1",
                            (key,)).fetchone()
        )
        c += rule("known_word", bool(known), "review", f"“{t}” is in ShiftNet", f"“{t}” is not in ShiftNet yet; a moderator will check it")

    if "target_sense_id" in p:
        ts = conn.execute("select * from senses where id = ?", (p["target_sense_id"],)).fetchone()
        ok = ts is not None and t is not None and (
            ts["lemma_key"] == norm(t)
            or bool(conn.execute("select 1 from sense_lemmas where sense_id = ? and lemma_key = ?", (ts["id"], norm(t))).fetchone())
        )
        c += rule("target_sense", ok, "error", None, "The target sense must be a sense of the related word")
        if ts is not None and ty in ("synonym", "antonym", "hypernym", "hyponym"):
            c += rule("same_pos", ts["pos"] == s["pos"], "review", None,
                      f"{s['id']} is a {s['pos']} and {ts['id']} a {ts['pos']}; a moderator will check the relation")
    elif "target_synset_id" in p:
        ok = t is not None and bool(conn.execute(
            "select 1 from synsets y, json_each(y.lemmas) m where y.id = ? and normalize_lemma(m.value) = ?",
            (p["target_synset_id"], norm(t)),
        ).fetchone())
        c += rule("target_synset", ok, "error", None, "The target synset must contain the related word")

    edge = relation_edge(conn, p)
    if edge is not None:
        if synset_above(conn, edge["parent"], edge["child"]):
            c += rule("no_cycle", False, "error", None, "This would make a synset its own ancestor in the taxonomy")
        elif synset_above(conn, edge["child"], edge["parent"]):
            c.append({"code": "taxonomy", "level": "note",
                      "message": "Already below that synset in the taxonomy: the relation is recorded, no edge is added"})
        else:
            c.append({"code": "taxonomy", "level": "pass",
                      "message": f"Adds {edge['child']} under {edge['parent']} in the taxonomy"})

    if ty in ("synonym", "antonym", "derived"):
        score = _suggestion_score(conn, s["id"], ty, t) if t else None
        c += rule("model_support", False, "review", None,
                  "Synonyms are always checked by a moderator: the model cannot tell a synonym from a sister term"
                  if ty == "synonym" else "Antonyms and derived forms are always checked by a moderator")
        if score is not None:
            c.append({"code": "model_note", "level": "note",
                      "message": f"LexSPLADE lists “{t}” as a near-synonym (score {score:.2f})"})
    elif ty is not None and t is not None:
        score = _suggestion_score(conn, s["id"], ty, t)
        c += rule("model_support", score is not None and score >= 0.6, "review",
                  f"LexSPLADE suggests this {ty} (score {score:.2f})" if score is not None else None,
                  "Not among LexSPLADE’s suggestions for this sense; a moderator will check it" if score is None
                  else f"LexSPLADE gives it a low score ({score:.2f}); a moderator will check it")
    return c


# ---------- Publishing ----------


def _contribution(conn: sqlite3.Connection, cid: str) -> dict | None:
    return conn.execute("select * from contributions where id = ?", (cid,)).fetchone()


def _decide(conn: sqlite3.Connection, cid: str, **fields: Any) -> dict:
    fields.setdefault("decided_at", db.now())
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"update contributions set {sets} where id = ?", [*fields.values(), cid])
    return _contribution(conn, cid)


def _publish_relation(conn: sqlite3.Connection, r: dict, m: str, reviewer: str | None, note: str | None) -> dict:
    p = r["payload"]
    ty, t = p["type"], p["target_lemma"]
    edge = relation_edge(conn, p)
    if ty == "synonym":
        conn.execute(
            """insert into sense_lemmas (sense_id, lemma, position)
               select ?, ?, coalesce(max(position) + 1, 0) from sense_lemmas where sense_id = ?""",
            (r["sense_id"], t, r["sense_id"]),
        )
        done: dict[str, Any] = {"table": "sense_lemmas", "lemma": t}
    else:
        conn.execute(
            """insert into relations (sense_id, type, target_lemma, position)
               select ?, ?, ?, coalesce(max(position) + 1, 0) from relations where sense_id = ? and type = ?""",
            (r["sense_id"], ty, t, r["sense_id"], ty),
        )
        done = {"table": "relations", "type": ty, "target_lemma": t}
    if edge is not None and not synset_above(conn, edge["child"], edge["parent"]):
        conn.execute(
            """insert into synset_hypernyms (synset_id, hypernym_id, position)
               select ?, ?, coalesce(max(position) + 1, 0) from synset_hypernyms where synset_id = ?""",
            (edge["child"], edge["parent"], edge["child"]),
        )
        done["synset_edge"] = edge
    return _decide(conn, r["id"], status="accepted", validation=m, published=done, reviewer_id=reviewer, review_note=note)


def _withdraw_relation(conn: sqlite3.Connection, r: dict) -> None:
    d = r["published"] or {}
    if d.get("table") == "sense_lemmas":
        conn.execute("delete from sense_lemmas where sense_id = ? and lemma = ?", (r["sense_id"], d["lemma"]))
    elif d.get("table") == "relations":
        conn.execute("delete from relations where sense_id = ? and type = ? and target_lemma = ?",
                     (r["sense_id"], d["type"], d["target_lemma"]))
    if "synset_edge" in d:
        conn.execute("delete from synset_hypernyms where synset_id = ? and hypernym_id = ?",
                     (d["synset_edge"]["child"], d["synset_edge"]["parent"]))


def publish(conn: sqlite3.Connection, r: dict, m: str, reviewer: str | None = None, note: str | None = None) -> dict:
    """Write an accepted contribution into the lexicon and mark it accepted."""
    if r["kind"] == "relation":
        return _publish_relation(conn, r, m, reviewer, note)
    p = r["payload"]
    if r["kind"] == "usage":
        sid, u = r["sense_id"], p
    else:
        sid = next_sense_id(conn, p["lemma"], p["pos"])
        conn.execute(
            """insert into senses (id, lemma, pos, gloss, examples, date_label, date_earliest, shift, source, source_type, validation)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, p["lemma"], p["pos"], p["gloss"], p.get("examples") or [], p["date_label"], p["date_earliest"],
             p["shift"], p["date_source"], p["source_type"], m),
        )
        conn.executemany(
            "insert into sense_parents (sense_id, parent_id, position) values (?, ?, ?)",
            [(sid, x, i) for i, x in enumerate(p.get("parents") or [])],
        )
        conn.execute("insert into sense_lemmas (sense_id, lemma, position) values (?, ?, 0)", (sid, p["lemma"]))
        db.renumber_senses(conn)
        u = p.get("usage")
    att = None
    if isinstance(u, dict):
        att = conn.execute(
            """insert into attestations (sense_id, source_id, quote, year, date_label, locator, validation, validated_at)
               values (?, ?, ?, ?, ?, ?, ?, ?) returning id""",
            (sid, source_for(conn, u["source"]), u["quote"], u.get("year"), u.get("date_label"), u.get("locator"), m, db.now()),
        ).fetchone()["id"]
        db.refresh_relevance(conn, [att])
    return _decide(conn, r["id"], status="accepted", validation=m, sense_id=sid, attestation_id=att,
                   reviewer_id=reviewer, review_note=note)


# ---------- Entry points (one transaction each) ----------


def _raise_on_errors(checks: Checks) -> None:
    if has_level(checks, "error"):
        raise ChecksFailed(checks)


def _payload(p: Any) -> dict:
    if not isinstance(p, dict):
        raise ContributionError("The proposal must be a JSON object")
    return p


def check_usage(conn: sqlite3.Connection, p: dict) -> Checks:
    """Run the automatic checks without submitting, for the form's "Check" button."""
    return usage_report(conn, clean_usage(_payload(p)))


def check_sense(conn: sqlite3.Connection, p: dict) -> Checks:
    return sense_report(conn, clean_sense(conn, _payload(p)))


def check_relation(conn: sqlite3.Connection, p: dict) -> Checks:
    return relation_report(conn, clean_relation(_payload(p)))


def _submit(conn: sqlite3.Connection, kind: str, payload: dict, checks: Checks, lemma: str, sense_id: str | None) -> dict:
    _raise_on_errors(checks)
    cid = conn.execute(
        """insert into contributions (contributor_id, kind, lemma, sense_id, payload, checks)
           values (?, ?, ?, ?, ?, ?) returning id""",
        (LOCAL_USER, kind, lemma, sense_id, payload, checks),
    ).fetchone()["id"]
    r = _contribution(conn, cid)
    if not has_level(checks, "review"):
        r = publish(conn, r, "automatic")
    return r


def submit_usage(conn: sqlite3.Connection, p: dict) -> dict:
    """Propose a usage: {sense_id, quote, year, date_label?, locator?, source: {kind, title, author?,
    publisher?, published_label?, published_year?, url?, identifier?, accessed_on?}}."""
    u = clean_usage(_payload(p)) or {}
    checks = usage_report(conn, u)
    _raise_on_errors(checks)
    s = conn.execute("select id, lemma from senses where id = ?", (u["sense_id"],)).fetchone()
    return _submit(conn, "usage", u, checks, s["lemma"], s["id"])


def submit_sense(conn: sqlite3.Connection, p: dict) -> dict:
    """Propose a sense: {lemma, pos, gloss, examples[], date_label, date_earliest, shift, date_source,
    source_type, parents[], usage?: {quote, year, date_label?, locator?, source}}."""
    s = clean_sense(conn, _payload(p))
    return _submit(conn, "sense", s, sense_report(conn, s), s.get("lemma") or "", None)


def submit_relation(conn: sqlite3.Connection, p: dict) -> dict:
    """Propose a relation: {sense_id, type, target_lemma, target_sense_id?, target_synset_id?, note?}."""
    v = clean_relation(_payload(p))
    if _len(v.get("note")) > 500:
        raise ContributionError("Note: at most 500 characters")
    checks = relation_report(conn, v)
    _raise_on_errors(checks)
    s = conn.execute("select id, lemma from senses where id = ?", (v["sense_id"],)).fetchone()
    return _submit(conn, "relation", v, checks, s["lemma"], s["id"])


def review_contribution(conn: sqlite3.Connection, cid: str, decision: str, note: str | None = None) -> dict:
    """Accept or reject a pending contribution, or confirm / withdraw an auto-accepted one.
    Accepting re-runs the blocking checks (the lexicon may have changed since submission)."""
    note = clean(note)
    if decision not in ("accept", "reject"):
        raise ContributionError("Decision must be accept or reject")
    if note is not None and len(note) > 1000:
        raise ContributionError("Review note: at most 1,000 characters")
    r = _contribution(conn, cid)
    if r is None:
        raise ContributionError("Contribution not found", 404)
    if decision == "reject" and note is None:
        raise ContributionError("Say why the contribution is rejected; the note is kept with it")

    report = {"usage": usage_report, "sense": sense_report, "relation": relation_report}[r["kind"]]
    if r["status"] == "pending" and decision == "accept":
        checks = report(conn, r["payload"], r["id"])
        _raise_on_errors(checks)
        conn.execute("update contributions set checks = ? where id = ?", (checks, r["id"]))
        return publish(conn, _contribution(conn, r["id"]), "manual", LOCAL_USER, note)
    if r["status"] == "pending":
        return _decide(conn, r["id"], status="rejected", reviewer_id=LOCAL_USER, review_note=note)
    if r["status"] == "accepted" and r["validation"] == "automatic" and decision == "accept":
        if r["kind"] != "relation":
            if r["attestation_id"]:
                conn.execute("update attestations set validation = 'manual', validated_at = ? where id = ?",
                             (db.now(), r["attestation_id"]))
                db.refresh_relevance(conn, [r["attestation_id"]])
            if r["kind"] == "sense":
                conn.execute("update senses set validation = 'manual' where id = ?", (r["sense_id"],))
        return _decide(conn, r["id"], validation="manual", reviewer_id=LOCAL_USER, review_note=note)
    if r["status"] == "accepted" and r["validation"] == "automatic":
        # Withdraw from the lexicon. A sense others have built on stays; edit it with the CLI.
        if r["kind"] == "relation":
            _withdraw_relation(conn, r)
            return _decide(conn, r["id"], status="rejected", validation=None, published=None,
                           reviewer_id=LOCAL_USER, review_note=note)
        if r["kind"] == "sense" and (
            conn.execute("select 1 from sense_parents where parent_id = ?", (r["sense_id"],)).fetchone()
            or conn.execute("select 1 from attestations where sense_id = ? and id is not ?",
                            (r["sense_id"], r["attestation_id"])).fetchone()
            or conn.execute("select 1 from contributions where sense_id = ? and id <> ? and status <> 'rejected'",
                            (r["sense_id"], r["id"])).fetchone()
        ):
            raise ContributionError("Other senses or usages depend on this sense; it cannot be withdrawn here", 409)
        if r["attestation_id"]:
            conn.execute("delete from attestations where id = ?", (r["attestation_id"],))
        if r["kind"] == "sense":
            conn.execute("delete from senses where id = ?", (r["sense_id"],))
            db.renumber_senses(conn)
        return _decide(conn, r["id"], status="rejected", validation=None, attestation_id=None,
                       sense_id=None if r["kind"] == "sense" else r["sense_id"],
                       reviewer_id=LOCAL_USER, review_note=note)
    raise ContributionError("This contribution has already been reviewed", 409)


# ---------- Reading ----------


def my_contributions(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    return conn.execute("select * from contributions order by created_at desc limit ?", (limit,)).fetchall()


def pending_for_sense(conn: sqlite3.Connection, sense_id: str) -> list[dict]:
    return conn.execute(
        """select * from contributions where sense_id = ? and kind = 'usage' and status = 'pending'
           order by created_at""",
        (sense_id,),
    ).fetchall()


def queue(conn: sqlite3.Connection, filter: str, limit: int = 100) -> list[dict]:
    if filter == "pending":
        q = "select * from contributions where status = 'pending' order by created_at"
    elif filter == "unconfirmed":
        q = "select * from contributions where status = 'accepted' and validation = 'automatic' order by decided_at desc"
    elif filter == "decided":
        q = "select * from contributions where reviewer_id is not null order by decided_at desc"
    else:
        raise ContributionError("filter must be pending, unconfirmed or decided")
    return conn.execute(f"{q} limit ?", (limit,)).fetchall()


def relation_suggestions(conn: sqlite3.Connection, sense_id: str, limit: int = 60) -> list[dict]:
    return conn.execute(
        """select id, sense_id, type, target_lemma, target_sense_id, target_synset_id, target_score, score, evidence, model, created_at
           from relation_suggestions where sense_id = ? order by score desc limit ?""",
        (sense_id, limit),
    ).fetchall()
