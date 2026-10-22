import pytest
from pydantic import ValidationError

from shiftnet_backend.models import CorpusUsage, SenseIn, SourceIn, sense_id_prefix, PartOfSpeech

BASE = dict(lemma="cloud", pos="noun", gloss="g", date_label="1990s", date_earliest=1990,
            source="s", source_type="corpus")


def test_root_has_no_parents_and_child_has_one():
    SenseIn(**BASE)
    SenseIn(**BASE, shift="metaphor", parents=[{"parent_id": "cloud.n.02"}])
    with pytest.raises(ValidationError):
        SenseIn(**BASE, shift="metaphor")
    with pytest.raises(ValidationError):
        SenseIn(**BASE, parents=[{"parent_id": "cloud.n.02"}])


def test_constraints_mirror_the_database():
    with pytest.raises(ValidationError):
        SenseIn(**{**BASE, "gloss": "   "})
    with pytest.raises(ValidationError):
        SenseIn(**BASE, obsolete_year=1900)
    with pytest.raises(ValidationError):
        SenseIn(**BASE, id="Cloud n 2")
    with pytest.raises(ValidationError):
        SourceIn(kind="website", title="x", url="ftp://example.org")
    with pytest.raises(ValidationError):
        SenseIn(**{**BASE, "pos": "noun phrase"})


def test_whitespace_is_cleaned():
    s = SenseIn(**{**BASE, "gloss": "  a  visible\nmass "}, examples=["", " the  sky "])
    assert s.gloss == "a visible mass"
    assert s.examples == ["the sky"]


def test_sense_id_prefix():
    assert sense_id_prefix("ice cream", PartOfSpeech.noun) == "ice_cream.n."
    assert sense_id_prefix("Nice", PartOfSpeech.adjective) == "nice.adj."


def test_usage_marking():
    u = CorpusUsage(doc_id="d", context="Back up to the cloud.", target_start=15, target_end=20)
    assert u.target == "cloud"
    assert u.marked() == "Back up to the <t> cloud </t>."
    with pytest.raises(ValidationError):
        CorpusUsage(doc_id="d", context="short", target_start=3, target_end=9)
