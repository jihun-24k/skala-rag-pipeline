"""Dependency-injection contracts for concrete LLM/RAG agent implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

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

AssessmentT = TypeVar("AssessmentT")


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    company_profile: CompanyProfile
    market_category: MarketCategory
    current_company: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class AnalysisResult(Generic[AssessmentT]):
    assessment: AssessmentT
    evidence: list[Evidence] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DecisionResult:
    decision: InvestmentDecision
    scores: dict[str, ScoreDetail]


MarketClassifier = Callable[[str, str], ClassificationResult]
TechnologyAnalyzer = Callable[
    [CompanyProfile, MarketCategory, str], AnalysisResult[TechAssessment]
]
MarketAnalyzer = Callable[
    [CompanyProfile, MarketCategory, str], AnalysisResult[MarketAssessment]
]
FinancialAnalyzer = Callable[
    [CompanyProfile, TechAssessment, MarketAssessment],
    AnalysisResult[FinancialAssessment],
]
DecisionMaker = Callable[
    [TechAssessment, MarketAssessment, FinancialAssessment, list[Evidence]],
    DecisionResult,
]
ReportWriter = Callable[
    [
        CompanyProfile,
        TechAssessment,
        MarketAssessment,
        FinancialAssessment,
        InvestmentDecision,
        list[Evidence],
    ],
    InvestmentReport,
]


@dataclass(frozen=True, slots=True)
class InvestmentAgents:
    classify_market: MarketClassifier
    analyze_technology: TechnologyAnalyzer
    analyze_market: MarketAnalyzer
    analyze_financials: FinancialAnalyzer
    make_decision: DecisionMaker
    write_report: ReportWriter
