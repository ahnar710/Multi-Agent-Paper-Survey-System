"""Shared data contracts used by every agent in the workflow.

Agents do not pass free-form chat messages to each other. They exchange these
validated objects so missing fields and invalid values fail visibly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


Score = Annotated[int, Field(ge=0, le=5)]


class StrictModel(BaseModel):
    """Base model that rejects fields not declared in the contract."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DocumentAccess(StrEnum):
    FULL_TEXT = "full_text"
    ABSTRACT_ONLY = "abstract_only"
    UNAVAILABLE = "unavailable"


class ScreeningDecision(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    REVIEW = "review"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class VerificationStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class RunStatus(StrEnum):
    CREATED = "created"
    SEARCHING = "searching"
    SCREENING = "screening"
    READING = "reading"
    VERIFYING = "verifying"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkItemStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PaperMetadata(StrictModel):
    """Stable identity and bibliographic information for one paper."""

    paper_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    authors: list[str] = Field(min_length=1)
    year: int = Field(ge=1800, le=2100)
    venue: str = Field(min_length=1)
    doi: str | None = None
    external_id: str | None = None
    source_url: HttpUrl | None = None
    document_access: DocumentAccess

    @model_validator(mode="after")
    def require_stable_source(self) -> "PaperMetadata":
        if not any((self.doi, self.external_id, self.source_url)):
            raise ValueError("doi、external_id 和 source_url 至少需要一项")
        return self


class Evidence(StrictModel):
    """One claim tied to a location in the source document."""

    claim: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    locator: str | None = None
    confidence: Confidence


class ResearchCard(StrictModel):
    """The complete, machine-checkable output of the reader agent."""

    paper: PaperMetadata

    gnss_domain: list[str] = Field(min_length=1)
    product_relevance: Score
    scientific_quality: Score
    novelty: Score
    screening_decision: ScreeningDecision
    screening_reason: str = Field(min_length=1)

    problem: str = Field(min_length=1)
    method: str = Field(min_length=1)
    data_and_experiment: str = Field(min_length=1)
    key_findings: list[str] = Field(min_length=1)
    limitations: list[str]
    applicable_conditions: list[str]
    comparison_baselines: list[str]
    technology_readiness: str = Field(min_length=1)

    product_implications: list[str]
    opportunities: list[str]
    risks: list[str]
    recommended_actions: list[str]

    evidence: list[Evidence] = Field(min_length=1)
    reader_agent_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    processed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    verification_status: VerificationStatus = VerificationStatus.PENDING
    quality_score: Score
    failure_reason: str | None = None

    @model_validator(mode="after")
    def enforce_source_level(self) -> "ResearchCard":
        if self.paper.document_access == DocumentAccess.FULL_TEXT:
            placeholder_markers = (
                "未指明",
                "未报告",
                "未提供",
                "不详",
                "unknown",
                "not reported",
                "not provided",
                "n/a",
            )
            missing = [
                item.claim
                for item in self.evidence
                if not item.locator
                or any(
                    marker in item.locator.casefold()
                    for marker in placeholder_markers
                )
            ]
            if missing:
                raise ValueError("全文研读的每条证据都必须包含页码、章节或图表定位")
        return self


class ResearchRun(StrictModel):
    """Persistent progress record for one end-to-end research request."""

    run_id: str = Field(min_length=1)
    topic_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    status: RunStatus = RunStatus.CREATED
    candidate_count: int = Field(default=0, ge=0)
    included_count: int = Field(default=0, ge=0)
    verified_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None


class CandidatePaper(StrictModel):
    """Paper metadata returned by a retrieval tool before agent screening."""

    paper: PaperMetadata
    abstract: str | None = None
    full_text: str | None = None
    full_text_source_url: HttpUrl | None = None
    retrieval_source: str = Field(min_length=1)
    retrieval_query: str = Field(min_length=1)
    retrieval_score: float | None = Field(default=None, ge=0)


class ScreeningResult(StrictModel):
    """Structured decision made by the screener for one candidate paper."""

    paper_id: str = Field(min_length=1)
    decision: ScreeningDecision
    relevance: Score
    scientific_quality: Score
    novelty: Score
    reason: str = Field(min_length=1)
    needs_full_text: bool


class ScreeningBatch(StrictModel):
    results: list[ScreeningResult]


class EvidenceVerification(StrictModel):
    evidence_index: int = Field(ge=0)
    claim_supported: bool
    locator_valid: bool
    strength_appropriate: bool
    reason: str = Field(min_length=1)


class VerificationReport(StrictModel):
    paper_id: str = Field(min_length=1)
    items: list[EvidenceVerification]
    status: VerificationStatus
    summary: str = Field(min_length=1)


class ReportCitation(StrictModel):
    paper_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    doi: str | None = None


class SynthesisReport(StrictModel):
    title: str = Field(min_length=1)
    research_question: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    evidence_scope: str = Field(min_length=1)
    main_themes: list[str]
    consensus_findings: list[str]
    conflicting_findings: list[str]
    research_gaps: list[str]
    product_implications: list[str]
    recommended_actions: list[str]
    limitations: list[str]
    citations: list[ReportCitation]


class WorkItem(StrictModel):
    work_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    status: WorkItemStatus = WorkItemStatus.PENDING
    payload: dict
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=2, ge=1)
    available_at: datetime
    lease_until: datetime | None = None
    worker_id: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class QualityGateResult(StrictModel):
    accepted: bool
    counts_toward_full_text_target: bool
    reasons: list[str]
