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
    max_attempts_per_agent: int = Field(default=4, ge=1, le=10)
    max_report_attempts: int = Field(default=2, ge=1, le=10)
    max_supervisor_steps: int = Field(default=20, ge=1, le=100)
    max_steps: int = Field(default=80, ge=4, le=300)
    max_errors: int = Field(default=4, ge=1, le=100)


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


REPORT_OUTLINE = (
    ('snapshot', '2. INVESTMENT SNAPSHOT'),
    ('business', '3. BUSINESS IDEA'),
    ('product', '4. PRODUCT & TECHNOLOGY'),
    ('market', '5. MARKET'),
    ('competition', '6. COMPETITION & MOAT'),
    ('traction', '7. TRACTION'),
    ('team', '8. TEAM'),
    ('financials', '9. FINANCIALS'),
    ('valuation', '10. VALUATION'),
    ('risks', '11. KEY RISKS'),
    ('decision', '12. INVESTMENT DECISION'),
    ('limitations', '13. LIMITATIONS'),
)


class ReportSection(DomainModel):
    key: Literal['snapshot', 'business', 'product', 'market', 'competition', 'traction',
                 'team', 'financials', 'valuation', 'risks', 'decision', 'limitations']
    findings: list[CitedClaim] = Field(default_factory=list)
    missing_facts: list[MissingFact] = Field(default_factory=list)


class FinancialChartPoint(DomainModel):
    period: str
    value: float = Field(allow_inf_nan=False)
    evidence_id: str


class FinancialChart(DomainModel):
    metric: str
    title: str
    unit: str
    statement_scope: str
    points: list[FinancialChartPoint] = Field(min_length=2)


class BusinessScore(DomainModel):
    criterion: Literal['team', 'market', 'technology', 'traction', 'moat', 'scalability']
    score: int | None = Field(default=None, ge=1, le=5)
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)


class BusinessAssessment(DomainModel):
    observed_score: float | None = None
    coverage_percent: float = 0
    signal: Literal['positive', 'concern', 'undetermined'] = 'undetermined'
    reason: str


class EvaluationReport(DomainModel):
    business_scores: list[BusinessScore] = Field(default_factory=list)
    business_assessment: BusinessAssessment | None = None
    classification: dict[str, str] = Field(default_factory=dict)
    financial_charts: list[FinancialChart] = Field(default_factory=list)
    company_name: str = ''
    summary: str
    perspectives: list[PerspectiveResult]
    limitations: list[str] = Field(default_factory=list)
    analysis_revision: int = Field(ge=0)
    references: dict[str, str] = Field(default_factory=dict)
    sections: list[ReportSection] = Field(default_factory=list)
    reference_details: dict[str, str] = Field(default_factory=dict)

    @property
    def title(self) -> str:
        return f'{self.company_name.strip()} 평가 보고서' if self.company_name.strip() else '기업 평가 보고서'


class QualityItem(DomainModel):
    criterion: Literal['groundedness', 'neutrality', 'bias', 'format']
    verdict: Literal['pass', 'fail', 'unknown']
    reason: str
    target: Literal['B', 'C', 'D', 'E', 'F'] | None = None
    questions: list[str] = Field(default_factory=list)


class QualityVerdict(DomainModel):
    items: list[QualityItem]
    report_revision: int = Field(ge=1)

    @model_validator(mode='after')
    def all_criteria(self):
        if sorted(i.criterion for i in self.items) != ['bias', 'format', 'groundedness', 'neutrality']:
            raise ValueError('Three quality criteria and the report format check are required')
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
