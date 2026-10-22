from datetime import date

import pytest

from shiftnet_backend import lexicon
from shiftnet_backend.discovery.pipeline import discover
from shiftnet_backend.discovery.store import (
    ReviewError, get_candidate, list_candidates, match, promote, reject, save_run,
)
from shiftnet_backend.models import PromoteIn

from .fakes import FakeEncoder

WEATHER = [
    "Dark grey clouds brought rain to the sky and the weather turned to storm, hiding the sun.",
    "A grey cloud crossed the sky and the weather promised rain and storm instead of sun.",
    "The storm cloud made the sky dark grey before the rain hid the sun.",
    "We watched the weather change as grey clouds filled the sky with rain and hid the sun.",
]
COMPUTING = [
    "Upload your files to the cloud for backup and online storage.",
    "Our data now lives on a cloud server instead of local storage.",
    "Cloud computing lets you upload data to an online server.",
    "Backup your files to cloud storage so the data is safe online.",
]


def _docs(dump, year, texts, n):
    for i in range(n):
        yield {"id": f"{dump}-{i}", "text": texts[i % len(texts)] + f" Item {i}.", "dump": dump,
               "url": f"https://site{i}.example.org/page", "date": f"{year}-05-0{1 + i % 9}T00:00:00Z"}


def _stream(dump, _files):
    if dump == "CC-MAIN-2013-20":
        return _docs(dump, 2013, WEATHER, 20)
    return list(_docs(dump, 2024, WEATHER, 6)) + list(_docs(dump, 2024, COMPUTING, 24))


@pytest.fixture
def run(conn):
    existing = lexicon.sense_texts(conn, "cloud")
    result = discover("cloud", FakeEncoder(), dumps=["CC-MAIN-2013-20", "CC-MAIN-2024-10"], per_dump=40,
                      existing=existing, stream=_stream, min_size=5)
    run_id = save_run(conn, result)
    return result, run_id


def test_pipeline_separates_senses_and_dates_them(run):
    result, _ = run
    assert len(result.usages) == 50
    by_terms = {c.cluster: {t.term for t in c.terms[:4]} for c in result.candidates}
    weather = next(c for c in result.candidates if by_terms[c.cluster] & {"rain", "sky", "storm", "grey"})
    computing = next(c for c in result.candidates if by_terms[c.cluster] & {"data", "storage", "files", "upload"})
    assert weather.size == 26 and computing.size == 24
    assert weather.first_seen == date(2013, 5, 1) and weather.year_counts == {"2013": 20, "2024": 6}
    assert computing.first_seen.year == 2024 and computing.year_counts == {"2024": 24}
    assert "cloud" not in {t.term for c in result.candidates for t in c.terms}  # the target itself is not a label
    # Matched against the seed's examples: "the clouds parted and the sun came out" / "back up your photos to the cloud".
    assert weather.nearest_sense_id == "cloud.n.02"


def test_review_flow(conn, run):
    _, run_id = run
    pending = list_candidates(conn, "cloud")
    assert len(pending) == 2 and all(c["status"] == "pending" for c in pending)
    weather, computing = sorted(pending, key=lambda c: c["first_seen"])

    detail = get_candidate(conn, weather["id"], usages=3)
    assert len(detail["typical_usages"]) == 3
    sims = [u["similarity"] for u in detail["typical_usages"]]
    assert sims == sorted(sims, reverse=True)

    ref = match(conn, weather["id"], attestations=2)
    assert (ref.status, ref.sense_id) == ("matched", "cloud.n.02")
    quoted = [a for a in lexicon.sense(conn, "cloud.n.02", 50)["attestations"] if a["validation"] == "automatic"]
    assert len(quoted) == 2
    assert quoted[0]["source"]["kind"] == "website" and quoted[0]["year"] == 2013

    ref = promote(conn, computing["id"], PromoteIn(pos="noun", gloss="online storage rented from a provider",
                                                   parent_ids=["cloud.n.06"], shift="narrowing"))
    assert ref.status == "promoted" and ref.sense_id == "cloud.n.07"
    s = lexicon.sense(conn, ref.sense_id)
    assert (s["date_label"], s["date_earliest"], s["validation"], s["source_type"]) == ("2024", 2024, "automatic", "corpus")
    assert "CC-MAIN-2024-10" in s["source"]
    assert len(s["examples"]) == 2 and len(s["attestations"]) == 3
    assert s["parents"][0]["id"] == "cloud.n.06"
    linked = conn.execute("select count(*) as n from public.corpus_usages where attestation_id is not null").fetchone()
    assert linked["n"] == 5

    with pytest.raises(ReviewError, match="already promoted"):
        reject(conn, computing["id"])
    assert list_candidates(conn, "cloud") == []
    assert len(list_candidates(conn, "cloud", status=None)) == 2


def test_reject_and_unknown_candidate(conn, run):
    c = list_candidates(conn, "cloud")[0]
    assert reject(conn, c["id"], "mixed").status == "rejected"
    with pytest.raises(ReviewError, match="No candidate"):
        match(conn, "00000000-0000-0000-0000-000000000000")


def test_staging_tables_are_private(conn, run):
    conn.execute("set local role anon")
    with pytest.raises(Exception, match="permission denied"):
        conn.execute("select * from public.sense_candidates")
