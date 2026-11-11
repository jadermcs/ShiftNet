"""Typed rows for the ShiftNet lexicon and the sense-discovery staging tables.

The enums and checks mirror schema.sql, so a row that validates here is accepted by
the database. Ids, sense numbers and branches that the database maintains are not part of the
input models.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator


class PartOfSpeech(StrEnum):
    noun = "noun"
    verb = "verb"
    adjective = "adjective"
    adverb = "adverb"


POS_TAG = {
    PartOfSpeech.noun: "n",
    PartOfSpeech.verb: "v",
    PartOfSpeech.adjective: "adj",
    PartOfSpeech.adverb: "adv",
}


class ShiftType(StrEnum):
    root = "root"
    broadening = "broadening"
    narrowing = "narrowing"
    metaphor = "metaphor"
    metonymy = "metonymy"
    amelioration = "amelioration"
    pejoration = "pejoration"
    other = "other"


class SourceType(StrEnum):
    dictionary = "dictionary"
    corpus = "corpus"
    citation = "citation"


class RelationType(StrEnum):
    antonym = "antonym"
    hypernym = "hypernym"
    hyponym = "hyponym"
    meronym = "meronym"
    holonym = "holonym"
    derived = "derived"


class ReferenceKind(StrEnum):
    book = "book"
    website = "website"
    article = "article"
    journal = "journal"
    newspaper = "newspaper"
    dictionary = "dictionary"
    corpus = "corpus"
    archive = "archive"
    other = "other"


class ValidationMethod(StrEnum):
    editorial = "editorial"
    automatic = "automatic"
    manual = "manual"


class CandidateStatus(StrEnum):
    pending = "pending"
    matched = "matched"
    promoted = "promoted"
    rejected = "rejected"


def _clean(v: str) -> str:
    """Trim and collapse whitespace, as private.clean does for contributions."""
    return re.sub(r"\s+", " ", v).strip()


def _not_blank(v: str) -> str:
    v = _clean(v)
    if not v:
        raise ValueError("must not be blank")
    return v


Text = Annotated[str, AfterValidator(_not_blank)]
SENSE_ID = re.compile(r"^[a-z0-9_'.\-]+\.(n|v|adj|adv)\.\d{2,}$")


class Row(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- Lexicon ----------


class SourceIn(Row):
    """A cited work (sources). Reused by URL, else identifier, else kind + title + author."""

    kind: ReferenceKind
    title: Text
    author: str | None = None
    publisher: str | None = None
    published_label: str | None = None
    published_year: int | None = None
    url: str | None = None
    identifier: str | None = None
    accessed_on: date | None = None

    @field_validator("url")
    @classmethod
    def _http(cls, v: str | None) -> str | None:
        if v is not None and not re.match(r"^https?://", v, re.I):
            raise ValueError("url must start with http:// or https://")
        return v


class AttestationIn(Row):
    """A dated quotation showing a sense in use (attestations)."""

    quote: Text
    source: SourceIn
    year: int | None = None
    date_label: str | None = None
    locator: str | None = None
    relevance_override: float | None = Field(default=None, ge=0, le=1)
    validation: ValidationMethod = ValidationMethod.editorial


class ParentIn(Row):
    """A parent link (sense_parents). The first parent is the branch the sense grows from."""

    parent_id: Text
    source: str | None = None


class RelationIn(Row):
    type: RelationType
    target_lemma: Text


class SenseIn(Row):
    """A sense with everything hanging off it. `id` is generated (cloud.n.05) when omitted."""

    id: str | None = None
    lemma: Text
    pos: PartOfSpeech
    gloss: Text
    examples: list[str] = Field(default_factory=list)
    date_label: Text
    date_earliest: int
    obsolete_year: int | None = None
    obsolete_label: str | None = None
    shift: ShiftType = ShiftType.root
    source: Text
    source_type: SourceType
    validation: ValidationMethod = ValidationMethod.editorial
    parents: list[ParentIn] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)  # synset members besides the lemma
    relations: list[RelationIn] = Field(default_factory=list)
    attestations: list[AttestationIn] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_shape(cls, v: str | None) -> str | None:
        if v is not None and not SENSE_ID.match(v):
            raise ValueError("id must look like lemma.pos.NN, e.g. cloud.n.02")
        return v

    @field_validator("examples", "synonyms")
    @classmethod
    def _drop_blank(cls, v: list[str]) -> list[str]:
        return [c for c in (_clean(x) for x in v) if c]

    @model_validator(mode="after")
    def _consistent(self) -> SenseIn:
        if self.obsolete_year is not None and self.obsolete_year < self.date_earliest:
            raise ValueError("obsolete_year must not be before date_earliest")
        if self.id is not None and self.id in {p.parent_id for p in self.parents}:
            raise ValueError("a sense cannot be its own parent")
        if (self.shift == ShiftType.root) != (not self.parents):
            raise ValueError("a root sense has no parents, and a sense with parents is not a root")
        return self


def sense_id_prefix(lemma: str, pos: PartOfSpeech) -> str:
    """'ice cream', noun → 'ice_cream.n.' (same rule as lexicon.next_sense_id)."""
    return re.sub(r"\s+", "_", lemma.strip()).lower() + "." + POS_TAG[pos] + "."


# ---------- Discovery ----------


class Term(BaseModel):
    term: str
    weight: float


class CorpusUsage(Row):
    """One occurrence of the lemma in a corpus document."""

    doc_id: str
    dump: str | None = None
    url: str | None = None
    crawled_on: date | None = None
    context: Text
    target_start: int = Field(ge=0)
    target_end: int

    @model_validator(mode="after")
    def _span(self) -> CorpusUsage:
        if not self.target_start < self.target_end <= len(self.context):
            raise ValueError("target span is outside the context")
        return self

    @property
    def target(self) -> str:
        return self.context[self.target_start : self.target_end]

    def marked(self) -> str:
        """The context with the target wrapped in LexSPLADE's <t>…</t> markers, with no spaces inside:
        a byte-level BPE (RoBERTa) would otherwise add stray space tokens the model was not trained on.
        WordPiece (BERT) tokenises both spellings the same way."""
        c = self.context
        return f"{c[: self.target_start]}<t>{self.target}</t>{c[self.target_end :]}"


class Candidate(BaseModel):
    """A cluster of usages: one candidate sense from a run."""

    cluster: int
    size: int
    terms: list[Term]
    first_seen: date | None = None
    last_seen: date | None = None
    year_counts: dict[str, int] = Field(default_factory=dict)
    nearest_sense_id: str | None = None
    nearest_score: float | None = None


class RunResult(BaseModel):
    """Everything a discovery run produces, ready to store."""

    lemma: str
    forms: list[str]
    corpus: str
    dumps: list[str]
    model: str
    params: dict
    candidates: list[Candidate]
    usages: list[CorpusUsage]
    assignments: list[int]  # per usage: cluster number, or -1 for noise
    similarities: list[float | None]
    usage_terms: list[list[Term]]
    # When only some usages are stored (bulk runs keep each cluster's typical and borderline ones):
    usage_count: int | None = None  # all usages clustered
    noise_count: int | None = None  # of which unclustered


class PromoteIn(Row):
    """What a reviewer adds to turn a candidate into a new sense."""

    pos: PartOfSpeech
    gloss: Text
    parent_ids: list[str] = Field(default_factory=list)
    shift: ShiftType | None = None  # default: other when it has a parent, else root
    date_label: str | None = None  # default: first crawl year it was seen in
    date_earliest: int | None = None
    examples: int = Field(default=2, ge=0, le=10)  # most typical usages copied into examples
    attestations: int = Field(default=3, ge=0, le=20)  # most typical usages quoted as attestations
    validation: ValidationMethod = ValidationMethod.automatic
    note: str | None = None


class CandidateRef(BaseModel):
    id: UUID
    status: CandidateStatus
    sense_id: str | None
