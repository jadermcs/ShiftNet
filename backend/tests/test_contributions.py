"""Proposed usages and senses: the automatic checks, publishing and review."""

import pytest

from shiftnet_backend import contributions as c
from shiftnet_backend import db as dbm
from shiftnet_backend.contributions import clean, isbn_ok, mentions

WEB = {"kind": "website", "title": "Example", "url": "https://example.org/clouds", "accessed_on": "2024-03-01"}


def usage(**kw):
    return {"sense_id": "cloud.n.06", "quote": "We moved every backup to the cloud last spring.", "year": 2012,
            "source": WEB, **kw}


def sense(**kw):
    return {"lemma": "Cloud", "pos": "noun", "gloss": "a large online store of personal photographs", "examples": [" a  photo cloud ", ""],
            "date_label": "2015", "date_earliest": 2015, "shift": "narrowing", "date_source": "Trade press",
            "source_type": "corpus", "parents": ["cloud.n.06"],
            "usage": {"quote": "All my holiday photos live in the cloud now.", "year": 2015, "source": WEB}, **kw}


def run(conn, fn, *args):
    with dbm.transaction(conn):
        return fn(conn, *args)


def codes(checks, level=None):
    return {x["code"] for x in checks if level is None or x["level"] == level}


def test_helpers():
    assert clean("  a\tb\n\nc  ") == "a b c" and clean("   ") is None
    assert isbn_ok("ISBN 978-0-306-40615-7") is True and isbn_ok("0-306-40615-2") is True
    assert isbn_ok("978-0-306-40615-8") is False and isbn_ok("shelfmark 12") is None
    assert mentions("The skies clouded over.", ["cloud"]) and mentions("a nicer day", ["nice"])
    assert not mentions("uncloudy", ["cloud"])  # prefix match at a word start only


def test_clean_usage_drops_unknown_keys_and_keeps_bad_numbers():
    u = c.clean_usage({"sense_id": " cloud.n.06 ", "year": "c. 1600", "evil": 1, "source": {"kind": "book", "published_year": "1600"}})
    assert u == {"sense_id": "cloud.n.06", "year": "c. 1600", "source": {"kind": "book", "published_year": 1600}}


def test_usage_with_no_flags_is_published_at_once(conn):
    r = run(conn, c.submit_usage, usage())
    assert (r["status"], r["validation"], r["reviewer_id"]) == ("accepted", "automatic", None)
    a = conn.execute("select * from attestations where id = ?", (r["attestation_id"],)).fetchone()
    assert a["validation"] == "automatic" and a["relevance"] > 0
    with pytest.raises(c.ChecksFailed) as e:  # the same quote again
        run(conn, c.submit_usage, usage(quote="We moved every backup to the CLOUD, last spring!"))
    assert codes(e.value.checks) == {"duplicate_quote"}

    confirmed = run(conn, c.review_contribution, r["id"], "accept", None)
    assert confirmed["validation"] == "manual"
    a2 = conn.execute("select validation, relevance from attestations where id = ?", (r["attestation_id"],)).fetchone()
    assert a2["validation"] == "manual" and a2["relevance"] > a["relevance"]


def test_antedating_waits_for_review_then_accepting_publishes(conn):
    r = run(conn, c.submit_usage, usage(year=1985))
    assert r["status"] == "pending" and "antedating" in codes(r["checks"], "review")
    assert [x["id"] for x in c.pending_for_sense(conn, "cloud.n.06")] == [r["id"]]
    assert [x["id"] for x in c.queue(conn, "pending")] == [r["id"]]
    a = run(conn, c.review_contribution, r["id"], "accept", "early trade press use")
    assert (a["status"], a["validation"], a["review_note"]) == ("accepted", "manual", "early trade press use")
    assert c.queue(conn, "pending") == [] and [x["id"] for x in c.queue(conn, "decided")] == [r["id"]]


def test_usage_errors(conn):
    bad = usage(quote="too short", year=3000, source={"kind": "website", "title": "x", "url": "ftp://x"})
    with pytest.raises(c.ChecksFailed) as e:
        run(conn, c.submit_usage, bad)
    assert {"quote_length", "year", "url_format"} <= codes(e.value.checks)
    assert all(x["level"] == "error" for x in e.value.checks)
    with pytest.raises(c.ChecksFailed) as e:
        run(conn, c.submit_usage, usage(sense_id="nope.n.01"))
    assert codes(e.value.checks) == {"sense_exists"}


def test_sense_is_published_with_its_usage_and_can_be_withdrawn(conn):
    checks = c.check_sense(conn, sense())
    assert not codes(checks, "error") and not codes(checks, "review"), checks
    r = run(conn, c.submit_sense, sense())
    assert (r["status"], r["validation"], r["sense_id"]) == ("accepted", "automatic", "cloud.n.07")
    assert r["payload"]["lemma"] == "cloud" and r["payload"]["examples"] == ["a photo cloud"]
    s = conn.execute("select sense_num, branch, validation from senses where id = 'cloud.n.07'").fetchone()
    assert s == {"sense_num": 7, "branch": 0, "validation": "automatic"}
    assert conn.execute("select count(*) as n from attestations where sense_id = 'cloud.n.07'").fetchone()["n"] == 1

    with pytest.raises(c.ChecksFailed) as e:
        run(conn, c.submit_sense, sense(gloss="A large online store of personal photographs."))
    assert "duplicate_gloss" in codes(e.value.checks)

    w = run(conn, c.review_contribution, r["id"], "reject", "not distinct from cloud.n.06")
    assert (w["status"], w["sense_id"], w["attestation_id"]) == ("rejected", None, None)
    assert not conn.execute("select 1 from senses where id = 'cloud.n.07'").fetchone()


def test_sense_review_flags(conn):
    r = run(conn, c.submit_sense, sense(lemma="cloudlet", parents=["cloud.n.06"], usage=None, date_earliest=1950, date_label="1950s"))
    assert r["status"] == "pending"
    assert {"known_word", "supporting_usage", "parents_older"} <= codes(r["checks"], "review")
    assert "parents_same_word" in codes(r["checks"], "note")
    with pytest.raises(c.ChecksFailed) as e:
        run(conn, c.submit_sense, sense(shift="root"))
    assert "root_parents" in codes(e.value.checks)
