import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from shiftnet_backend.discovery import bulk
from shiftnet_backend.discovery.lemmatize import learn, vocabulary
from shiftnet_backend.discovery.text import context_at

from .fakes import BagEncoder

# A tiny "WordNet": plurals and -ing forms of a few nouns, enough to learn rules from.
STEMS = ["table", "chair", "tree", "branch", "office", "train", "paper", "storm", "server", "file",
         "window", "garden", "river", "letter", "market", "street", "school", "ticket", "basket", "bottle"]
LEXICON = {s: {s} for s in STEMS} | {s + "s": {s} for s in STEMS} | {s + "ing": {s} for s in STEMS} | {
    "cloud": {"cloud"}, "clouds": {"cloud"}, "leaf": {"leaf"}, "leave": {"leave"}, "leaving": {"leave"},
    "leaves": {"leaf", "leave"}, "mice": {"mouse"}, "mouse": {"mouse"},
}


def fake_morphy(form: str) -> dict[str, set[str]]:
    return {"n": LEXICON[form]} if form in LEXICON else {}


def test_learnt_rules_lemmatise_unknown_forms():
    counts = {f: 50 for s in STEMS for f in (s, s + "s", s + "ing")} | {
        "selfie": 40, "selfies": 60, "doomscroll": 10, "doomscrolling": 30, "mice": 9, "mouse": 30,
        "leaves": 80, "leaf": 30, "leave": 60, "zork": 7, "zorks": 5, "selfi": 2,
    }
    lem = learn(counts, fake_morphy, min_count=5, min_support=5)
    assert {r[:2] for r in lem.rules} == {("s", ""), ("ing", "")}
    assert lem.of["selfies"] == ("selfie",)  # "selfi" is too rare to be the lemma
    assert lem.of["doomscrolling"] == ("doomscroll",)
    assert lem.of["mice"] == ("mouse",)  # irregular: from the dictionary
    assert lem.of["leaves"] == ("leave", "leaf")  # ambiguous, most frequent first
    assert lem.of["zorks"] == ("zork",)
    assert lem.of["zork"] == ("zork",)


def test_vocabulary_skips_function_words_and_names():
    counts = {"the": 1000, "bank": 100, "banks": 50, "london": 90, "river": 80}
    caps = {"london": 89, "bank": 5}
    lem = learn(counts, lambda f: {"n": {"bank"}} if f in ("bank", "banks") else {}, min_count=1)
    got = vocabulary(lem, counts, caps, top=10)
    assert [l for l, _ in got] == ["bank", "river"]
    assert got[0][1] == 150


def test_context_and_fit():
    text = "Intro line.\n\nWe walked along the bank of the wide river at dawn. Next sentence here."
    s = text.index("bank")
    occ = context_at(text, s, s + 4)
    assert occ.context == "We walked along the bank of the wide river at dawn."
    assert occ.context[occ.start : occ.end] == "bank"
    assert context_at("Menu: bank.", 6, 10) is None
    offs = bulk.regex_offsets([occ.context])[0]
    ctx, a, b = bulk.fit(occ.context, occ.start, occ.end, offs, budget=5)
    assert ctx[a:b] == "bank" and len(bulk.regex_offsets([ctx])[0]) <= 5
    assert ctx == "along the bank of the"  # centred: two words each side


TREE = ["The {w} on the old oak tree turned red and yellow in the autumn wind.",
        "Green {w} covered every branch of the tall tree in the garden near the river."]
OFFICE = ["She {w} the office early to catch the last train home every evening.",
          "He usually {w} the office at six and takes the train to the station."]
WEATHER = ["Dark grey {w} brought rain and storm over the sky before the sun set today.",
           "Heavy {w} filled the sky with rain while the storm moved across the valley."]
COMPUTING = ["Back up every photos file to the {w} so the server keeps your data safe online.",
             "Our data now lives on a {w} server and every file syncs online automatically."]
WORDS = ["oak", "tree", "red", "yellow", "autumn", "wind", "green", "branch", "garden", "river",
         "office", "early", "train", "home", "evening", "six", "station", "dark", "grey", "rain", "storm",
         "sky", "sun", "back", "photos", "heavy", "valley", "file", "server", "data", "safe", "online", "syncs"]
DUMPS = ["CC-MAIN-2013-20", "CC-MAIN-2024-10"]


def _docs(dump: str, year: int, n_computing: int) -> pa.Table:
    rows = []

    def add(template, w):
        i = len(rows)
        sentence = template.format(w=w)[:-1] + f" on day {i}."  # distinct: repeated contexts are dropped
        rows.append({"text": f"Page {i}. " + sentence + " End of the page here now.",
                     "id": f"{dump}-{i}", "dump": dump, "url": f"https://s{i}.example.org/",
                     "date": f"{year}-03-{1 + i % 27:02d}T00:00:00Z", "file_path": "x"})

    for i in range(30):
        add(TREE[i % 2], "leaves")
        add(TREE[i % 2], "leaf")
        add(OFFICE[i % 2], "leaves")
        add(OFFICE[i % 2], "leaving")
        add(WEATHER[i % 2], "clouds")
    for i in range(n_computing):
        add(COMPUTING[i % 2], "cloud")
    return pa.Table.from_pylist(rows)


@pytest.fixture(scope="module")
def workdir(tmp_path_factory):
    root = tmp_path_factory.mktemp("bulk")
    for dump, year, n in ((DUMPS[0], 2013, 0), (DUMPS[1], 2024, 40)):
        (root / "mirror" / "data" / dump).mkdir(parents=True)
        pq.write_table(_docs(dump, year, n), root / "mirror" / "data" / dump / "000.parquet", row_group_size=20)
    w = root / "work"
    bulk.download(w, DUMPS, docs=10_000, local=root / "mirror")
    bulk.count(w, workers=2)
    bulk.build_vocab(w, top=50, min_count=5, morphy=fake_morphy)
    bulk.sample(w, per_lemma=400, workers=2)
    bulk.encode(w, BagEncoder(WORDS), shard=0, shards=2, chunk=37)
    bulk.encode(w, BagEncoder(WORDS), shard=1, shards=2, chunk=37)
    bulk.cluster_all(w, min_size=5, min_usages=10, min_support=10, workers=2)
    return w


def _runs(w):
    return {r["run"]["lemma"]: r for r in bulk.runs(w)}


def test_vocab_counts_and_ambiguity(workdir):
    v = json.loads((workdir / "vocab.json").read_text())
    by = {e["lemma"]: e for e in v["lemmas"]}
    assert {"cloud", "leaf", "leave", "page"} <= set(by)
    assert "the" not in by
    assert sorted(v["forms"]["leaves"]) == ["leaf", "leave"]
    assert by["cloud"]["by_dump"] == [30, 70]
    assert by["leaf"]["by_dump"] == [90, 90]  # 30 "leaf" plus all 60 "leaves": offered to both lemmas


def test_ambiguous_forms_resolved_in_context(workdir):
    runs = _runs(workdir)
    leaf, leave = runs["leaf"]["run"], runs["leave"]["run"]
    assert leaf["usage_count"] == 120 and leave["usage_count"] == 120  # own forms 60, plus 60 "leaves" each
    leaf_text = " ".join(u["context"] for u in leaf["usages"])
    leave_text = " ".join(u["context"] for u in leave["usages"])
    assert "tree" in leaf_text and "office" not in leaf_text
    assert "office" in leave_text and "tree" not in leave_text


def test_clusters_split_senses_and_keep_few_usages(workdir):
    run = _runs(workdir)["cloud"]["run"]
    assert run["usage_count"] == 100 and len(run["candidates"]) == 2
    weather, computing = sorted(run["candidates"], key=lambda c: c["first_seen"])
    assert weather["year_counts"] == {"2013": 30, "2024": 30} and computing["year_counts"] == {"2024": 40}
    assert {t["term"] for t in computing["terms"][:4]} & {"server", "data", "file", "online"}
    assert len(run["usages"]) == 2 * (15 + 5)  # typical and borderline usages of each candidate
    assert sorted(run["forms"]) == ["cloud", "clouds"]


def test_stages_resume(workdir):
    before = sorted(p.stat().st_mtime_ns for p in (workdir / "runs").glob("*.gz"))
    bulk.cluster_all(workdir, min_size=5, min_usages=10, min_support=10, workers=1)
    assert sorted(p.stat().st_mtime_ns for p in (workdir / "runs").glob("*.gz")) == before
    status = bulk.describe(workdir)
    assert all(a == b for a, b in (v.split("/") for v in status["encode"].values()))
    assert sum(status["sample"].values()) == bulk.load_usages(workdir).num_rows


def test_import_stores_runs_with_nearest_sense(workdir, database_url, conn):
    from shiftnet_backend import db

    def factory(write):
        return db.transaction(database_url) if write else db.connect(database_url)

    n = bulk.import_runs(factory, workdir, "test", lambda: BagEncoder(WORDS))
    assert n == len(_runs(workdir))
    assert bulk.import_runs(factory, workdir, "test", lambda: BagEncoder(WORDS)) == 0  # already imported under this tag
    r = conn.execute("select usage_count, params from public.discovery_runs where lemma = 'cloud'").fetchone()
    assert r["usage_count"] == 100 and r["params"]["bulk"] == "test"
    first = conn.execute(
        "select nearest_sense_id, first_seen from public.sense_candidates where lemma = 'cloud' order by first_seen"
    ).fetchone()
    assert first["first_seen"].year == 2013 and first["nearest_sense_id"] == "cloud.n.02"
    stored = conn.execute(
        "select count(*) as n from public.corpus_usages u join public.discovery_runs r on r.id = u.run_id "
        "where r.lemma = 'cloud'"
    ).fetchone()["n"]
    assert stored == 40
