import psycopg
import pytest

from shiftnet_backend import lexicon
from shiftnet_backend.models import AttestationIn, SenseIn, SourceIn

NEW = dict(lemma="cloud", pos="noun", gloss="a group of servers rented on demand", date_label="2006",
           date_earliest=2006, shift="narrowing", source="Trade press", source_type="corpus",
           parents=[{"parent_id": "cloud.n.06", "source": "Trade press"}])


def test_seed_follows_the_root_rule(conn):
    """SenseIn requires root ⇔ no parents; the existing data must satisfy it so it can be re-saved."""
    bad = conn.execute(
        """select id, shift from public.senses s
           where (shift = 'root') = exists (select 1 from public.sense_parents p where p.sense_id = s.id)"""
    ).fetchall()
    assert bad == []


def test_new_sense_gets_next_id_and_number(conn):
    (sid,) = lexicon.save_senses(conn, [SenseIn(**NEW, synonyms=["cloud hosting"])])
    assert sid == "cloud.n.07"
    row = conn.execute("select sense_num, branch, validation from public.senses where id = %s", (sid,)).fetchone()
    assert row["sense_num"] == 7 and row["validation"] == "editorial"
    word = {s["id"]: s for s in lexicon.word(conn, "Cloud")}
    assert word[sid]["parents"][0]["id"] == "cloud.n.06"
    assert word[sid]["synonyms"] == ["cloud hosting"]
    assert conn.execute("select * from public.search_lemmas('cloud host')").fetchone()["sense_id"] == sid


def test_update_replaces_links_and_keeps_attestations(conn):
    att = AttestationIn(quote="Move it all to the cloud.", year=2008,
                        source=SourceIn(kind="website", title="example.org", url="https://example.org/a"))
    (sid,) = lexicon.save_senses(conn, [SenseIn(**NEW, attestations=[att])])
    lexicon.save_senses(conn, [SenseIn(**{**NEW, "id": sid, "gloss": "rented servers",
                                          "parents": [{"parent_id": "cloud.n.05"}, {"parent_id": "cloud.n.06"}]},
                                       attestations=[att])])
    s = lexicon.sense(conn, sid)
    assert s["gloss"] == "rented servers"
    assert [p["id"] for p in s["parents"]] == ["cloud.n.05", "cloud.n.06"]
    assert len(s["attestations"]) == 1  # the same quote from the same work is stored once
    assert s["attestations"][0]["relevance"] > 0  # computed by the database trigger
    assert sid in {c["id"] for c in lexicon.sense(conn, "cloud.n.05")["children"]}


def test_source_is_reused_by_url(conn):
    s1 = lexicon.source_for(conn, SourceIn(kind="website", title="A", url="https://Example.org/x"))
    s2 = lexicon.source_for(conn, SourceIn(kind="website", title="B", url="https://example.org/x"))
    s3 = lexicon.source_for(conn, SourceIn(kind="book", title="Clouds", author="Howard"))
    assert s1 == s2 != s3
    assert s3 == lexicon.source_for(conn, SourceIn(kind="book", title="clouds", author="howard"))


def test_batch_with_parent_later_in_the_batch(conn):
    child = SenseIn(id="zork.n.02", lemma="zork", pos="noun", gloss="b", date_label="2001", date_earliest=2001,
                    shift="metaphor", source="s", source_type="corpus", parents=[{"parent_id": "zork.n.01"}])
    root = SenseIn(id="zork.n.01", lemma="zork", pos="noun", gloss="a", date_label="1999", date_earliest=1999,
                   source="s", source_type="corpus")
    assert lexicon.save_senses(conn, [child, root]) == ["zork.n.02", "zork.n.01"]
    assert [s["sense_num"] for s in lexicon.word(conn, "zork")] == [1, 2]


def test_unknown_parent_fails_the_whole_batch(conn):
    bad = SenseIn(**{**NEW, "parents": [{"parent_id": "nope.n.01"}]})
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with conn.transaction():
            lexicon.save_senses(conn, [SenseIn(**NEW), bad])
    assert conn.execute("select count(*) as n from public.senses where id like 'cloud.n.0_' and id > 'cloud.n.06'").fetchone()["n"] == 0


def test_search_falls_back_to_close_spellings(conn):
    assert lexicon.search(conn, "clowd")[0] == {"lemma": "cloud", "kind": "word", "sense_id": None, "close_spelling": True}
