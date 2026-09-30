"""Data contracts shared by API, service, and agent layers."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


FinancialSource = Literal["dart", "fsc", "kind"]
FINANCIAL_FIELDS = (
    "revenue",
    "operating_income",
    "net_income",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "current_assets",
    "current_liabilities",
    "cash_and_cash_equivalents",
    "operating_cash_flow",
    "total_funding",
)


class ApiStatus(str, Enum):
    """A source response status; absence and operational errors stay distinct."""

    AVAILABLE = "available"
    COMPANY_NOT_FOUND = "company_not_found"
    FINANCIAL_NOT_FOUND = "company_found_but_financial_not_found"
    API_ERROR = "api_error"
    NOT_CONFIGURED = "not_configured"


class CompanyRef(BaseModel):
    company_id: str
    company_name: str
    business_number: str | None = None
    corporation_number: str | None = None
    dart_corp_code: str | None = None
    listed: bool | None = None


class FinancialValue(BaseModel):
    value: float | None = None
    unit: str | None = None
    source: FinancialSource
    as_of: str | None = None
    previous_value: float | None = None
    previous_as_of: str | None = None
    report_type: Literal["first_quarter", "half_year", "third_quarter", "annual"] | None = None
    statement_scope: Literal["consolidated", "separate"] | None = None
    receipt_no: str | None = None
    raw_value: Any | None = Field(
        default=None,
        description="Original provider value retained for audit/debugging.",
    )


class FinancialData(BaseModel):
    revenue: FinancialValue | None = None
    operating_income: FinancialValue | None = None
    net_income: FinancialValue | None = None
    total_assets: FinancialValue | None = None
    total_liabilities: FinancialValue | None = None
    total_equity: FinancialValue | None = None
    current_assets: FinancialValue | None = None
    current_liabilities: FinancialValue | None = None
    cash_and_cash_equivalents: FinancialValue | None = None
    operating_cash_flow: FinancialValue | None = None
    total_funding: FinancialValue | None = None

    def missing_fields(self) -> list[str]:
        return [
            field
            for field in FINANCIAL_FIELDS
            if (item := getattr(self, field)) is None or item.value is None
        ]


class FinancialMetrics(BaseModel):
    revenue_growth: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    asset_growth: float | None = None
    runway_months: float | None = None
    runway_status: Literal["actual", "proxy", "unavailable"] = "unavailable"


class FinancialApiResponse(BaseModel):
    """Provider-neutral response used between API clients and the collector."""

    status: ApiStatus
    data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class SourceCollectionReport(BaseModel):
    source: Literal["dart", "fsc", "kind"]
    status: ApiStatus
    requested_fields: list[str] = Field(default_factory=list)
    accepted_fields: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class FinancialCollectionResult(BaseModel):
    financials: FinancialData
    source_reports: list[SourceCollectionReport] = Field(default_factory=list)


class FinancialAgentOutput(BaseModel):
    revenue: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    total_equity: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    cash_and_cash_equivalents: float | None = None
    operating_cash_flow: float | None = None
    total_funding: float | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    as_of: str | None = None
    status: Literal["available", "partial", "unavailable"]
