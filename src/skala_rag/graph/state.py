"""State contracts and reducers for the investment-analysis graph."""

from __future__ import annotations

from typing import Annotated

from typing_extensions import NotRequired, TypedDict

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
