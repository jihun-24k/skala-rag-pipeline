"""State contracts and reducers for the investment-analysis graph."""

from __future__ import annotations

from typing import Annotated

from typing_extensions import NotRequired, TypedDict

from skala_rag.models import (
    CompanyProfile,
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
    query: str
    as_of_date: str


class InvestmentState(InvestmentInput, total=False):
    company_profile: CompanyProfile
    market_category: MarketCategory
    tech_analysis: TechAssessment
    market_analysis: MarketAssessment
    financial_analysis: FinancialAssessment
    evidence: Annotated[list[Evidence], merge_evidence]
    decision: InvestmentDecision
    scores: dict[str, ScoreDetail]
    report: InvestmentReport

class InvestmentOutput(TypedDict):
    company_profile: CompanyProfile
    market_category: MarketCategory
    tech_analysis: TechAssessment
    market_analysis: MarketAssessment
    financial_analysis: FinancialAssessment
    evidence: list[Evidence]
    decision: InvestmentDecision
    scores: dict[str, ScoreDetail]
    report: InvestmentReport
