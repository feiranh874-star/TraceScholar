"""Persistent document records and evidence-oriented API contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SourceIdentifiers(BaseModel):
    arxiv_id: str | None = None
    doi: str | None = None


class PageRecord(BaseModel):
    page: int = Field(ge=1)
    text: str
    char_count: int = Field(ge=0)
    needs_ocr: bool
    bbox: tuple[float, float, float, float] | None = None


class SectionRecord(BaseModel):
    section_id: str
    number: str | None = None
    title: str
    level: int = Field(ge=1)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    page_char_start: int = Field(ge=0)


class SourceReference(BaseModel):
    paper_id: str
    work_id: str
    version_label: str | None = None
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    section_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None


class TextChunkRecord(BaseModel):
    chunk_id: str
    text: str
    char_count: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=1)
    source: SourceReference


class EvidenceRecord(BaseModel):
    """Retrieval result contract used by later RAG and answer stages."""

    evidence_id: str
    text: str
    score: float | None = None
    source: SourceReference


class RetrievalRequest(BaseModel):
    """A paper-grounded search request used before model generation."""

    question: str = Field(min_length=2, max_length=500)
    paper_ids: list[str] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=6, ge=1, le=12)


class LibraryMentionRequest(BaseModel):
    """Search all indexed papers; pagination limits display, not search scope."""

    question: str = Field(min_length=1, max_length=500)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=50)

    @field_validator("question")
    @classmethod
    def nonempty_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("输入不能为空")
        return value.strip()


class ComparisonRequest(BaseModel):
    """A comparison must explicitly name at least two papers."""

    question: str = Field(min_length=2, max_length=500)
    paper_ids: list[str] = Field(min_length=2, max_length=5)
    limit: int = Field(default=10, ge=2, le=15)

    @field_validator("paper_ids")
    @classmethod
    def paper_ids_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("paper_ids must be unique")
        return value


class RetrievalEvidenceRecord(EvidenceRecord):
    paper_title: str | None = None
    filename: str
    section_title: str | None = None


class RetrievalResponse(BaseModel):
    question: str
    total_candidates: int = Field(ge=0)
    items: list[RetrievalEvidenceRecord] = Field(default_factory=list)


class AnswerCitationRecord(RetrievalEvidenceRecord):
    citation_id: str


class AnswerResponse(BaseModel):
    question: str
    answer: str | None = None
    insufficient: bool
    provider: str | None = None
    model: str | None = None
    citations: list[AnswerCitationRecord] = Field(default_factory=list)
    items: list[RetrievalEvidenceRecord] = Field(default_factory=list)
    total_candidates: int = Field(default=0, ge=0)


class AgentStepRecord(BaseModel):
    tool: str
    status: Literal["done", "skipped"]
    detail: str


class AgentResponse(AnswerResponse):
    intent: Literal["definition", "method", "result", "comparison", "summary", "general"]
    route: Literal["retrieve_only", "grounded_answer"]
    steps: list[AgentStepRecord] = Field(default_factory=list)


class PaperMetadataRecord(BaseModel):
    paper_id: str
    work_id: str
    filename: str
    sha256: str
    page_count: int = Field(ge=1)
    title: str | None = None
    author: str | None = None
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    notes: str = Field(default="", max_length=4000)
    collection_ids: list[str] = Field(default_factory=list)
    identifiers: SourceIdentifiers = Field(default_factory=SourceIdentifiers)
    version_label: str | None = None
    version_number: int | None = Field(default=None, ge=1)
    parse_status: Literal["ready", "needs_ocr"]
    needs_ocr_pages: list[int] = Field(default_factory=list)
    section_count: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=0, ge=0)
    created_at: str
    warnings: list[str] = Field(default_factory=list)


class VersionRelation(BaseModel):
    kind: Literal["none", "related", "older_version", "newer_version", "same_version"]
    related_count: int = Field(ge=0)
    latest_paper_id: str
    latest_version_label: str | None = None
    recommendation: Literal["none", "keep_existing_newer", "keep_uploaded_newer", "keep_both"]

