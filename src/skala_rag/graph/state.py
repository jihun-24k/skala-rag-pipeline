"""State contracts and reducers for the investment-analysis graph."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import TypeAdapter
from typing_extensions import NotRequired, TypedDict

from skala_rag.models.orchestration import (
    ErrorInfo, EvaluationReport, EvaluationSummary, Limits, PerspectiveResult,
    QualityVerdict, RunStatus, SupervisorDecision, TaskRequest, TaskResult,
)

from skala_rag.models import (
    CompanyProfile,
    CompetitorAnalysis,
    Evidence,
    FinancialAssessment,
    InvestmentDecision,
    InvestmentReport,
    MarketAssessment,
    MarketCategory,
    ScoreDetail,
    TechAssessment,
)


def merge_evidence(current: list[Evidence], update: list[Evidence]) -> list[Evidence]:
    """Merge parallel evidence writes while preserving first-seen order."""

    merged: dict[str, Evidence] = {item.evidence_id: item for item in current}
    for item in update:
        merged.setdefault(item.evidence_id, item)
    return list(merged.values())


class InvestmentInput(TypedDict):
    query: NotRequired[str]
    as_of_date: str
    candidate_companies: NotRequired[list[str | dict[str, object]]]
    current_index: NotRequired[int]


class InvestmentState(InvestmentInput, total=False):
    current_company: dict[str, object]
    company_profile: CompanyProfile
    market_category: MarketCategory
    tech_analysis: TechAssessment
    market_analysis: MarketAssessment
    competitor_analysis: CompetitorAnalysis
    financial_analysis: FinancialAssessment
    evidence: Annotated[list[Evidence], merge_evidence]
    decision: InvestmentDecision
    scores: dict[str, ScoreDetail]
    report: InvestmentReport

class InvestmentOutput(TypedDict):
    current_company: NotRequired[dict[str, object]]
    company_profile: CompanyProfile
    market_category: MarketCategory
    tech_analysis: TechAssessment
    market_analysis: MarketAssessment
    competitor_analysis: CompetitorAnalysis
    financial_analysis: FinancialAssessment
    evidence: list[Evidence]
    decision: InvestmentDecision
    scores: dict[str, ScoreDetail]
    report: InvestmentReport


_output_adapter = TypeAdapter(InvestmentOutput)


def to_storage_payload(output: InvestmentOutput) -> dict[str, Any]:
    """그래프 결과를 JSON 호환 값으로 검증·변환해 저장 계층에 넘긴다.

    날짜는 ISO 문자열로 바뀌고 Pydantic 모델은 일반 dict가 된다. 이 함수는
    DB 연결이나 INSERT를 하지 않는다. 호출자가 이후 저장 여부를 결정한다.
    """
    validated = _output_adapter.validate_python(output)
    return _output_adapter.dump_python(validated, mode="json")


def merge_task_results(current: dict[str, TaskResult], update: dict[str, TaskResult]) -> dict[str, TaskResult]:
    merged = dict(current)
    for key, result in update.items():
        if key in merged and merged[key] != result:
            raise ValueError(f'Conflicting result for task attempt {key}')
        merged[key] = result
    return merged


class SupervisorState(TypedDict, total=False):
    # Payload and recovery identity; source documents and event history stay external.
    run_id: str
    thread_id: str
    trace_id: str
    schema_version: str
    input_fingerprint: str
    config_version: str
    index_version: str | None
    query: str
    as_of_date: str
    candidate_companies: list[str | dict[str, object]]
    company_profile: CompanyProfile
    market_category: MarketCategory
    current_company: dict[str, object]
    perspectives: dict[str, PerspectiveResult]
    evidence: list[Evidence]
    active_evidence_ids: list[str]
    evaluation_summary: EvaluationSummary | None
    report: EvaluationReport | None
    quality_result: QualityVerdict | None
    # Workers write only reducer-protected task results; Supervisor/collector own the rest.
    task_results: Annotated[dict[str, TaskResult], merge_task_results]
    collected_tasks: list[str]
    pending_tasks: list[TaskRequest]
    task_status: dict[str, str]
    next_action: SupervisorDecision
    attempts: dict[str, int]
    stagnant_agents: list[str]
    research_sufficient: bool | None
    analysis_revision: int
    report_revision: int
    step_count: int
    supervisor_count: int
    limits: Limits
    status: RunStatus
    termination_reason: str | None
    error_count: int
    last_error: ErrorInfo | None
    task_errors: dict[str, ErrorInfo]
    retry_counts: dict[str, int]
