"""Structured outputs shared by all investment-analysis agents."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    """Strict base model so malformed agent output fails at a node boundary."""

    model_config = ConfigDict(extra="forbid")


class MissingFact(DomainModel):
    field: str
    reason: str
    attempted_queries: list[str] = Field(default_factory=list)
    sources_checked: list[str] = Field(default_factory=list)


class Evidence(DomainModel):
    evidence_id: str
    claim_text: str
    stance: Literal["support", "contradict", "unknown"]
    source_type: str
    source_grade: Literal["A", "B", "C", "D", "E"]
    source_uri: str
    locator: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # 검색기가 확인한 메타데이터를 보존한다. 이 값들은 점수 상한과 시점 검증에 쓰고,
    # model_dump(mode="json")으로 추후 저장 계층에 그대로 전달할 수 있다.
    company_id: str | None = None
    published_at: date | None = None
    source_event_id: str | None = None
    independent: bool | None = None
    value: float | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    metric_names: list[str] = Field(default_factory=list)
    topic: str | None = None
    paper_id: str | None = None
    patent_family_id: str | None = None
    paper_company_author: bool | None = None
    paper_core_relevant: bool | None = None
    paper_has_results: bool | None = None


class CompanyProfile(DomainModel):
    company_id: str
    company_name: str
    physical_ai_type: str
    stage: str
    as_of_date: date


class MarketCategory(DomainModel):
    industry: str
    sub_industry: str
    target_market: list[str] = Field(default_factory=list)
    customer_type: list[str] = Field(default_factory=list)
    analysis_scope: list[str] = Field(default_factory=list)


class TechAssessment(DomainModel):
    product_summary: str
    core_technology: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    patents: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    technical_risks: list[str] = Field(default_factory=list)
    team: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_facts: list[MissingFact] = Field(default_factory=list)


class MarketAssessment(DomainModel):
    tam: str | None = None
    sam: str | None = None
    som: str | None = None
    customer_segments: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    market_risks: list[str] = Field(default_factory=list)
    traction: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_facts: list[MissingFact] = Field(default_factory=list)


class FinancialAssessment(DomainModel):
    # D가 재무제표 확보를 명시하지 않으면 E는 채점하지 않는다.
    status: Literal["available", "unavailable"] = "unavailable"
    revenue: str | None = None
    operating_income: str | None = None
    total_assets: str | None = None
    total_liabilities: str | None = None
    total_funding: str | None = None
    burn_rate: str | None = None
    runway_months: float | None = Field(default=None, ge=0.0)
    funding_need: str | None = None
    financial_risks: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_facts: list[MissingFact] = Field(default_factory=list)


class ScoreDetail(DomainModel):
    dimension: str
    score: float = Field(ge=0.0, le=100.0)
    weight: float = Field(ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    missing_status: str | None = None


class InvestmentDecision(DomainModel):
    decision: Literal["투자", "조건부 투자", "추가 실사", "투자 제외"]
    total_score: float | None = Field(default=None, ge=0.0, le=100.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    investment_reasons: list[str] = Field(default_factory=list)
    counter_arguments: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class InvestmentReport(DomainModel):
    summary: str
    technology: str
    market_competition: str
    financials: str
    risks: str
    decision: str
    references: list[str] = Field(default_factory=list)
