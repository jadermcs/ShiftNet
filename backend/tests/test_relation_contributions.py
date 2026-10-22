"""The relation contribution flow in SQL, called as signed-in users (role authenticated + JWT sub)."""

import uuid
from contextlib import contextmanager

import psycopg
import pytest
from psycopg.types.json import Jsonb

USER, TRUSTED, MOD = (str(uuid.uuid4()) for _ in range(3))


@contextmanager
def as_user(conn, uid):
    conn.execute("select set_config('request.jwt.claim.sub', %s, true)", (uid,))
    conn.execute("set local role authenticated")
    yield  # on an error the enclosing savepoint's rollback undoes the role change
    conn.execute("reset role")


def rpc(conn, uid, fn, *args):
    with as_user(conn, uid):
        return conn.execute(f"select * from public.{fn}({', '.join(['%s'] * len(args))})", args).fetchone()


def submit(conn, uid, **p):
    return rpc(conn, uid, "submit_relation", Jsonb(p))


def codes(checks, level=None):
    return {c["code"] for c in checks if level is None or c["level"] == level}


@pytest.fixture
def db(conn):
    for u in (USER, TRUSTED, MOD):
        conn.execute("insert into auth.users (id) values (%s)", (u,))
    conn.execute("insert into public.moderators (user_id) values (%s)", (MOD,))
    for _ in range(3):  # TRUSTED has 3 accepted contributions and none rejected
        conn.execute(
            """insert into public.contributions (contributor_id, kind, status, lemma, payload, validation, decided_at)
               values (%s, 'usage', 'accepted', 'cloud', '{}', 'manual', now())""",
            (TRUSTED,),
        )
    conn.execute("insert into public.synsets (id, pos, lemmas, gloss) values ('wn-gadget-n', 'noun', '{gadget}', 'a small device')")
    rows = [
        ("mouse.n.01", "hypernym", "animal", None, "wn-animal-n", 0.76),
        ("mouse.n.04", "hypernym", "gadget", None, "wn-gadget-n", 0.70),
        ("mouse.n.04", "meronym", "button", None, None, 0.40),
        ("mouse.n.01", "synonym", "rat", None, None, 0.64),
    ]
    for sid, ty, t, ts, sy, score in rows:
        conn.execute(
            """insert into public.relation_suggestions (sense_id, type, target_lemma, target_sense_id, target_synset_id, score, model)
               values (%s, %s, %s, %s, %s, %s, 'test')""",
            (sid, ty, t, ts, sy, score),
        )
    return conn


def test_supported_relation_from_trusted_contributor_is_published_with_taxonomy_edge(db):
    c = submit(db, TRUSTED, sense_id="mouse.n.04", type="hypernym", target_lemma="gadget", target_synset_id="wn-gadget-n")
    assert (c["status"], c["validation"], c["kind"]) == ("accepted", "automatic", "relation")
    assert "model_support" in codes(c["checks"], "pass") and "taxonomy" in codes(c["checks"], "pass")
    assert db.execute("select 1 from public.relations where sense_id = 'mouse.n.04' and type = 'hypernym' and target_lemma = 'gadget'").fetchone()
    edge = db.execute("select position from public.synset_hypernyms where synset_id = 'mouse.n.04' and hypernym_id = 'wn-gadget-n'").fetchone()
    assert edge == {"position": 1}  # pointing device stays the breadcrumb path

    # A moderator withdraws it: the relation and the edge go.
    w = rpc(db, MOD, "review_contribution", c["id"], "reject", "not a hypernym")
    assert (w["status"], w["validation"], w["published"]) == ("rejected", None, None)
    assert not db.execute("select 1 from public.relations where sense_id = 'mouse.n.04' and target_lemma = 'gadget'").fetchone()
    assert not db.execute("select 1 from public.synset_hypernyms where hypernym_id = 'wn-gadget-n'").fetchone()


def test_untrusted_or_unsupported_relations_wait_for_review(db):
    c = submit(db, USER, sense_id="mouse.n.04", type="hypernym", target_lemma="gadget", target_synset_id="wn-gadget-n")
    assert c["status"] == "pending" and "trusted" in codes(c["checks"], "review")
    c = submit(db, TRUSTED, sense_id="mouse.n.04", type="meronym", target_lemma="button")
    assert c["status"] == "pending"
    assert {"model_support", "known_word"} <= codes(c["checks"], "review")  # low score, and "button" is not in ShiftNet

    accepted = rpc(db, MOD, "review_contribution", c["id"], "accept", None)
    assert (accepted["status"], accepted["validation"]) == ("accepted", "manual")
    assert db.execute("select 1 from public.relations where sense_id = 'mouse.n.04' and type = 'meronym' and target_lemma = 'button'").fetchone()


def test_synonyms_always_reviewed_and_published_as_synset_members(db):
    c = submit(db, TRUSTED, sense_id="mouse.n.01", type="synonym", target_lemma="rat")
    assert c["status"] == "pending"
    assert "model_support" in codes(c["checks"], "review") and "model_note" in codes(c["checks"], "note")
    rpc(db, MOD, "review_contribution", c["id"], "accept", "fine for the sample")
    members = [r["lemma"] for r in db.execute("select lemma from public.sense_lemmas where sense_id = 'mouse.n.01' order by position")]
    assert members[-1] == "rat"


def test_redundant_edge_and_cycle(db):
    c = submit(db, TRUSTED, sense_id="mouse.n.01", type="hypernym", target_lemma="animal", target_synset_id="wn-animal-n")
    assert c["status"] == "accepted"
    assert any(x["code"] == "taxonomy" and x["level"] == "note" for x in c["checks"])  # already under rodent › … › animal
    assert db.execute("select count(*) as n from public.synset_hypernyms where synset_id = 'mouse.n.01'").fetchone()["n"] == 1

    with pytest.raises(psycopg.errors.RaiseException) as e, db.transaction():
        submit(db, TRUSTED, sense_id="mouse.n.01", type="hyponym", target_lemma="animal", target_synset_id="wn-animal-n")
    assert "no_cycle" in e.value.diag.message_detail


def test_errors_block_the_submission(db):
    submit(db, USER, sense_id="mouse.n.04", type="meronym", target_lemma="button")
    for p, code in [
        (dict(sense_id="mouse.n.04", type="meronym", target_lemma="Button"), "not_duplicate"),
        (dict(sense_id="mouse.n.04", type="meronym", target_lemma="mouse"), "not_self"),
        (dict(sense_id="mouse.n.04", type="cousin", target_lemma="rat"), "relation_type"),
        (dict(sense_id="mouse.n.04", type="hypernym", target_lemma="gadget", target_sense_id="cloud.n.02"), "target_sense"),
        (dict(sense_id="mouse.n.04", type="hypernym", target_lemma="gizmo", target_synset_id="wn-gadget-n"), "target_synset"),
    ]:
        with pytest.raises(psycopg.errors.RaiseException) as e, db.transaction():
            submit(db, USER, **p)
        assert code in e.value.diag.message_detail, p


def test_check_relation_does_not_store(db):
    checks = rpc(db, USER, "check_relation", Jsonb(dict(sense_id="mouse.n.01", type="hypernym", target_lemma="animal")))["check_relation"]
    assert "model_support" in codes(checks, "pass")
    assert db.execute("select count(*) as n from public.contributions where kind::text = 'relation'").fetchone()["n"] == 0


def test_usage_review_still_goes_through_the_original_function(db):
    cid = db.execute(
        """insert into public.contributions (contributor_id, kind, lemma, sense_id, payload)
           values (%s, 'usage', 'cloud', 'cloud.n.02', '{}') returning id""",
        (USER,),
    ).fetchone()["id"]
    r = rpc(db, MOD, "review_contribution", cid, "reject", "no source")
    assert r["status"] == "rejected" and r["review_note"] == "no source"
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="already been reviewed"), db.transaction():
        rpc(db, MOD, "review_contribution", cid, "reject", "again")


def test_suggestions_are_for_signed_in_users_only(db):
    with as_user(db, USER):
        assert db.execute("select count(*) as n from public.relation_suggestions").fetchone()["n"] == 4
    db.execute("set local role anon")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select * from public.relation_suggestions")
