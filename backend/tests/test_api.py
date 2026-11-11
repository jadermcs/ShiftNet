"""The HTTP API the web app uses."""

import pytest
from starlette.testclient import TestClient

from shiftnet_backend.api import create_app


@pytest.fixture
def client(db_path):
    return TestClient(create_app())


def test_word_page_shapes(client):
    senses = client.get("/api/word/cloud").json()
    assert [s["id"] for s in senses][:2] == ["cloud.n.01", "cloud.n.02"]
    s2 = senses[1]
    assert s2["attestation_count"] == 4 and [a["rank"] for a in s2["top_attestations"]] == [1, 2, 3]
    assert s2["top_attestations"][0]["source"]["kind"]
    s6 = client.get("/api/sense/cloud.n.06").json()
    assert s6["parents"][0]["parent"]["id"] == "cloud.n.05" and s6["synset_id"] == "cloud.n.06"
    assert {"lemma": "cloud computing", "position": 1} in s6["synonyms"]
    assert client.get("/api/sense/nope.n.01").json() is None


def test_search_and_taxonomy(client):
    assert client.get("/api/search", params={"q": "clo"}).json()[0] == {
        "lemma": "cloud", "kind": "word", "sense_id": None, "pos": "noun · verb", "meta": "8 senses"}
    assert client.get("/api/close-spellings", params={"q": "clowd"}).json()[0]["lemma"] == "cloud"
    assert client.get("/api/resolve", params={"q": "CLOUD"}).json() == {"kind": "word", "lemma": "cloud", "sense_id": None}
    path = client.get("/api/synset/mouse.n.04/path").json()
    assert path[0]["id"] == "wn-entity-n" and path[-1] == {**path[-1], "id": "mouse.n.04", "depth": 0}
    assert client.get("/api/stats").json()["overview"]["senses"] == 29


def test_contribution_round_trip(client):
    usage = {"sense_id": "cloud.n.06", "quote": "We moved every backup to the cloud in 1985.", "year": 1985,
             "source": {"kind": "book", "title": "Networks", "identifier": "978-0-306-40615-7"}}
    checks = client.post("/api/contributions/check/usage", json=usage).json()
    assert any(x["code"] == "antedating" and x["level"] == "review" for x in checks)
    r = client.post("/api/contributions/usage", json=usage).json()
    assert r["status"] == "pending"
    assert [x["id"] for x in client.get("/api/contributions/queue/pending").json()] == [r["id"]]
    bad = client.post("/api/contributions/usage", json={**usage, "quote": "short"})
    assert bad.status_code == 422 and bad.json()["checks"][0]["code"] == "quote_length"
    no_note = client.post(f"/api/contributions/{r['id']}/review", json={"decision": "reject"})
    assert no_note.status_code == 400 and "Say why" in no_note.json()["message"]
    ok = client.post(f"/api/contributions/{r['id']}/review", json={"decision": "accept", "note": None}).json()
    assert ok["validation"] == "manual"
    assert client.get("/api/contributions").json()[0]["id"] == r["id"]
    assert client.get("/api/me").json() == {"id": "local", "moderator": True}


from .test_discovery import run  # noqa: E402,F401  (fixture: a discovery run for "cloud")


def test_discovery_words_and_review(client, run):
    words = client.get("/api/discovery/words").json()
    assert (words["total_words"], words["pending_words"]) == (1, 1)
    w = words["words"][0]
    assert (w["lemma"], w["rank"], w["in_lexicon"]) == ("cloud", 1, True) and w["pending"] == w["candidates"] == 2
    assert client.get("/api/discovery/words", params={"q": "zz"}).json()["matches"] == 0

    detail = client.get("/api/discovery/word/Cloud").json()
    cands = detail["candidates"]
    assert len(cands) == 2 and cands[0]["size"] >= cands[1]["size"]
    assert cands[0]["typical_usages"] and isinstance(cands[0]["first_seen"], str)
    assert client.get("/api/discovery/word/nope").json() is None

    weather = next(c for c in cands if c["nearest_sense_id"] == "cloud.n.02")
    other = next(c for c in cands if c is not weather)
    r = client.post(f"/api/discovery/candidates/{weather['id']}/match", json={})
    assert r.json() == {"id": weather["id"], "status": "matched", "sense_id": "cloud.n.02"}
    quoted = [a for a in client.get("/api/sense/cloud.n.02/attestations").json() if a["quote"].startswith(("Dark", "A grey", "The storm", "We watched"))]
    assert len(quoted) == 3 and {a["validation"] for a in quoted} == {"manual"}  # reviewed by a person
    again = client.post(f"/api/discovery/candidates/{weather['id']}/reject", json={"note": "x"})
    assert again.status_code == 409
    bad = client.post(f"/api/discovery/candidates/{other['id']}/promote", json={"pos": "noun", "gloss": ""})
    assert bad.status_code == 400 and "gloss" in bad.json()["message"]
    p = client.post(f"/api/discovery/candidates/{other['id']}/promote",
                    json={"pos": "noun", "gloss": "online storage", "parent_ids": ["cloud.n.06"], "shift": "narrowing"}).json()
    assert p["status"] == "promoted" and p["sense_id"] == "cloud.n.07"
    after = client.get("/api/discovery/words").json()  # the summary cache was cleared by the reviews
    assert after["pending_words"] == 0
    promoted = client.get("/api/sense/cloud.n.07").json()
    assert promoted["gloss"] == "online storage" and promoted["validation"] == "manual"
    assert {a["validation"] for a in client.get("/api/sense/cloud.n.07/attestations").json()} == {"manual"}
