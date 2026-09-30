"""State contracts and reducers for the investment-analysis graph."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import TypeAdapter
from typing_extensions import TypedDict

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
    current_company: dict[str, object]
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
