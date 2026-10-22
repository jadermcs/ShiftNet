from shiftnet_backend.discovery.relations import RelationSuggester, SenseInfo, Suggestion, WordFilter, _bare, inverses

from .fakes import FakeEncoder


class Words(WordFilter):
    """Every alphabetic vocabulary term is a word of any part of speech."""

    def __init__(self):
        self.wn = None
        self._cache = {}


def test_inverses_need_a_target_sense():
    senses = {
        "mouse.n.01": SenseInfo("mouse.n.01", "mouse", "noun", "a small rodent"),
        "animal.n.01": SenseInfo("animal.n.01", "animal", "noun", "a living organism", known={("hyponym", "dog")}),
    }
    found = [
        Suggestion("mouse.n.01", "hypernym", "animal", 0.8, {}, "animal.n.01", 0.64),
        Suggestion("mouse.n.01", "hypernym", "pet", 0.7, {}),  # not in ShiftNet: no inverse
        Suggestion("mouse.n.01", "meronym", "tail", 0.9, {}),
    ]
    (inv,) = inverses(found, senses)
    assert (inv.sense_id, inv.type, inv.target_lemma, inv.target_sense_id) == ("animal.n.01", "hyponym", "mouse", "mouse.n.01")
    assert inv.score == round(0.8 * 0.64**0.5, 4)
    senses["animal.n.01"].known.add(("hyponym", "mouse"))
    assert inverses(found, senses) == []


def test_bare_gloss():
    assert _bare("a small rodent") == "small rodent"
    assert _bare("to make unclear") == "make unclear"
    assert _bare("remote servers") == "remote servers"


def test_word_filter_fallback_without_wordnet():
    w = Words()
    assert w.lemma("animal", "noun") == "animal"
    assert w.lemma("##s", "noun") is None and w.lemma("of", "noun") is None


def test_suggest_shapes_and_skips_known_relations():
    s = SenseInfo("cloud.n.06", "cloud", "noun", "remote data storage on an online server",
                  ["upload your files to the cloud"], known={("synonym", "storage")})
    out = RelationSuggester(FakeEncoder(), words=Words(), per_relation=3).suggest(s)
    assert out and {x.type for x in out} <= {"synonym", "hypernym", "meronym"}
    assert all(0 <= x.score <= 1 and x.sense_id == s.id for x in out)
    assert ("synonym", "storage") not in {(x.type, x.target_lemma) for x in out}
    assert not {x.target_lemma for x in out} & {"cloud", "clouds"}
    assert all(x.evidence["method"] in ("substitutes", "pattern") for x in out)
