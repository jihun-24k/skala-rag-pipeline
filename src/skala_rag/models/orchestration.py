"""Validated task, control, error and neutral evaluation contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from skala_rag.models.investment import CompanyProfile, DomainModel, Evidence, MarketCategory, MissingFact

AgentName = Literal['A', 'B', 'C', 'D', 'E', 'F', 'G']
View = Literal['technology', 'market', 'stakeholders', 'domain']
VIEWS: tuple[View, ...] = ('technology', 'market', 'stakeholders', 'domain')
RunStatus = Literal['running', 'interrupted', 'passed', 'incomplete', 'failed']


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ErrorInfo(DomainModel):
    error_id: str
    node: str
    task_id: str
    attempt: int = Field(ge=1)
    type: str
    message: str
    retryable: bool
    ts: AwareDatetime = Field(default_factory=utc_now)


class Limits(DomainModel):
    max_attempts_per_agent: int = Field(default=3, ge=1, le=10)
    max_report_attempts: int = Field(default=3, ge=1, le=10)
    max_supervisor_steps: int = Field(default=20, ge=1, le=100)
    max_steps: int = Field(default=60, ge=4, le=300)
    max_errors: int = Field(default=6, ge=1, le=100)


class TaskRequest(DomainModel):
    task_id: str
    agent: AgentName
    attempt: int = Field(ge=1)
    questions: list[str] = Field(min_length=1)
    reason: str
    based_on_revision: int = Field(ge=0)


class CitedClaim(DomainModel):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class PerspectiveResult(DomainModel):
    view: View
    findings: list[CitedClaim] = Field(default_factory=list)
    missing_facts: list[MissingFact] = Field(default_factory=list)


class ResearchResult(DomainModel):
    perspectives: list[PerspectiveResult] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class ClassificationPayload(DomainModel):
    company_profile: CompanyProfile
    market_category: MarketCategory
    current_company: dict[str, object] | None = None


class EvaluationSummary(DomainModel):
    perspectives: list[PerspectiveResult]
    limitations: list[str] = Field(default_factory=list)
    analysis_revision: int = Field(ge=0)


class EvaluationReport(DomainModel):
    summary: str
    perspectives: list[PerspectiveResult]
    limitations: list[str] = Field(default_factory=list)
    analysis_revision: int = Field(ge=0)
    references: dict[str, str] = Field(default_factory=dict)


class QualityItem(DomainModel):
    criterion: Literal['groundedness', 'neutrality', 'bias', 'coverage']
    verdict: Literal['pass', 'fail', 'unknown']
    reason: str
    target: Literal['B', 'C', 'D', 'E', 'F'] | None = None
    questions: list[str] = Field(default_factory=list)


class QualityVerdict(DomainModel):
    items: list[QualityItem]
    report_revision: int = Field(ge=1)

    @model_validator(mode='after')
    def all_criteria(self):
        if sorted(i.criterion for i in self.items) != ['bias', 'coverage', 'groundedness', 'neutrality']:
            raise ValueError('Exactly one verdict for each of the four criteria is required')
        return self

    @property
    def passed(self) -> bool:
        return all(item.verdict == 'pass' for item in self.items)


class SupervisorDecision(DomainModel):
    action: Literal['research', 'retry', 'synthesize', 'write', 'evaluate', 'finish']
    targets: list[AgentName] = Field(default_factory=list)
    reason: str
    questions: list[str] = Field(default_factory=list)
    based_on_revision: int = Field(ge=0)
    terminal_status: Literal['passed', 'incomplete', 'failed'] | None = None
    sufficient: bool | None = None


Payload = ClassificationPayload | ResearchResult | EvaluationSummary | EvaluationReport | QualityVerdict


class TaskResult(DomainModel):
    request: TaskRequest
    status: Literal['succeeded', 'insufficient', 'unavailable', 'failed']
    payload: Payload | None = None
    error: ErrorInfo | None = None
    started_at: AwareDatetime
    completed_at: AwareDatetime

    @model_validator(mode='after')
    def valid_outcome(self):
        if self.status == 'failed' and (self.error is None or self.payload is not None):
            raise ValueError('Failed task requires an error and no payload')
        if self.status != 'failed' and (self.error is not None or self.payload is None):
            raise ValueError('Non-failed task requires a payload and no error')
        if self.completed_at < self.started_at:
            raise ValueError('Task completion precedes its start')
        return self
