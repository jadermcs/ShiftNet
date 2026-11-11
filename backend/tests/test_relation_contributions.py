"""The relation contribution flow (single local user, who also reviews)."""

import pytest

from shiftnet_backend import contributions as c
from shiftnet_backend import db as dbm


def submit(conn, **p):
    with dbm.transaction(conn):
        return c.submit_relation(conn, p)


def review(conn, cid, decision, note=None):
    with dbm.transaction(conn):
        return c.review_contribution(conn, cid, decision, note)


def codes(checks, level=None):
    return {x["code"] for x in checks if level is None or x["level"] == level}


@pytest.fixture
def db(conn):
    conn.execute("insert into synsets (id, pos, lemmas, gloss) values ('wn-gadget-n', 'noun', '[\"gadget\"]', 'a small device')")
    rows = [
        ("mouse.n.01", "hypernym", "animal", None, "wn-animal-n", 0.76),
        ("mouse.n.04", "hypernym", "gadget", None, "wn-gadget-n", 0.70),
        ("mouse.n.04", "meronym", "button", None, None, 0.40),
        ("mouse.n.01", "synonym", "rat", None, None, 0.64),
    ]
    conn.executemany(
        """insert into relation_suggestions (sense_id, type, target_lemma, target_sense_id, target_synset_id, score, model)
           values (?, ?, ?, ?, ?, ?, 'test')""",
        rows,
    )
    return conn


def test_supported_relation_is_published_with_taxonomy_edge_and_can_be_withdrawn(db):
    r = submit(db, sense_id="mouse.n.04", type="hypernym", target_lemma="gadget", target_synset_id="wn-gadget-n")
    assert (r["status"], r["validation"], r["kind"]) == ("accepted", "automatic", "relation")
    assert "model_support" in codes(r["checks"], "pass") and "taxonomy" in codes(r["checks"], "pass")
    assert db.execute("select 1 from relations where sense_id = 'mouse.n.04' and type = 'hypernym' and target_lemma = 'gadget'").fetchone()
    edge = db.execute("select position from synset_hypernyms where synset_id = 'mouse.n.04' and hypernym_id = 'wn-gadget-n'").fetchone()
    assert edge == {"position": 1}  # pointing device stays the breadcrumb path

    w = review(db, r["id"], "reject", "not a hypernym")
    assert (w["status"], w["validation"], w["published"]) == ("rejected", None, None)
    assert not db.execute("select 1 from relations where sense_id = 'mouse.n.04' and target_lemma = 'gadget'").fetchone()
    assert not db.execute("select 1 from synset_hypernyms where hypernym_id = 'wn-gadget-n'").fetchone()


def test_unsupported_relations_wait_for_review(db):
    r = submit(db, sense_id="mouse.n.04", type="meronym", target_lemma="button")
    assert r["status"] == "pending"
    assert {"model_support", "known_word"} <= codes(r["checks"], "review")  # low score, and "button" is not in ShiftNet

    accepted = review(db, r["id"], "accept")
    assert (accepted["status"], accepted["validation"], accepted["reviewer_id"]) == ("accepted", "manual", "local")
    assert db.execute("select 1 from relations where sense_id = 'mouse.n.04' and type = 'meronym' and target_lemma = 'button'").fetchone()


def test_synonyms_always_reviewed_and_published_as_synset_members(db):
    r = submit(db, sense_id="mouse.n.01", type="synonym", target_lemma="rat")
    assert r["status"] == "pending"
    assert "model_support" in codes(r["checks"], "review") and "model_note" in codes(r["checks"], "note")
    review(db, r["id"], "accept", "fine for the sample")
    members = [x["lemma"] for x in db.execute("select lemma from sense_lemmas where sense_id = 'mouse.n.01' order by position")]
    assert members[-1] == "rat"


def test_redundant_edge_and_cycle(db):
    r = submit(db, sense_id="mouse.n.01", type="hypernym", target_lemma="animal", target_synset_id="wn-animal-n")
    assert r["status"] == "accepted"
    assert any(x["code"] == "taxonomy" and x["level"] == "note" for x in r["checks"])  # already under rodent › … › animal
    assert db.execute("select count(*) as n from synset_hypernyms where synset_id = 'mouse.n.01'").fetchone()["n"] == 1

    with pytest.raises(c.ChecksFailed) as e:
        submit(db, sense_id="mouse.n.01", type="hyponym", target_lemma="animal", target_synset_id="wn-animal-n")
    assert "no_cycle" in codes(e.value.checks)


def test_errors_block_the_submission(db):
    submit(db, sense_id="mouse.n.04", type="meronym", target_lemma="button")
    for p, code in [
        (dict(sense_id="mouse.n.04", type="meronym", target_lemma="Button"), "not_duplicate"),
        (dict(sense_id="mouse.n.04", type="meronym", target_lemma="mouse"), "not_self"),
        (dict(sense_id="mouse.n.04", type="cousin", target_lemma="rat"), "relation_type"),
        (dict(sense_id="mouse.n.04", type="hypernym", target_lemma="gadget", target_sense_id="cloud.n.02"), "target_sense"),
        (dict(sense_id="mouse.n.04", type="hypernym", target_lemma="gizmo", target_synset_id="wn-gadget-n"), "target_synset"),
    ]:
        with pytest.raises(c.ChecksFailed) as e:
            submit(db, **p)
        assert code in codes(e.value.checks), p
    assert db.execute("select count(*) as n from contributions").fetchone()["n"] == 1


def test_check_relation_does_not_store(db):
    checks = c.check_relation(db, dict(sense_id="mouse.n.01", type="hypernym", target_lemma="animal"))
    assert "model_support" in codes(checks, "pass")
    assert db.execute("select count(*) as n from contributions").fetchone()["n"] == 0


def test_rejecting_needs_a_note_and_happens_once(db):
    r = submit(db, sense_id="mouse.n.04", type="meronym", target_lemma="button")
    with pytest.raises(c.ContributionError, match="Say why"):
        review(db, r["id"], "reject")
    assert review(db, r["id"], "reject", "no source")["review_note"] == "no source"
    with pytest.raises(c.ContributionError, match="already been reviewed") as e:
        review(db, r["id"], "reject", "again")
    assert e.value.status == 409
