from __future__ import annotations

import pytest

from skala_rag.agents.financial_agent.agent.financial_agent import (
    FinancialAgent,
    financial_agent,
    get_financial_data,
    get_financial_data_batch,
)
from skala_rag.agents.financial_agent.models.schemas import (
    ApiStatus,
    CompanyRef,
    FinancialApiResponse,
    FinancialData,
    FinancialValue,
)
from skala_rag.agents.financial_agent.service import FinancialCalculator, FinancialCollector, FinancialNormalizer


class StubClient:
    def __init__(
        self,
        source: str,
        data: dict[str, object] | None = None,
        status: ApiStatus = ApiStatus.AVAILABLE,
    ) -> None:
        self.source = source
        self.data = data or {}
        self.status = status
        self.calls: list[list[str]] = []

    def fetch(self, company: CompanyRef, fields: list[str]) -> FinancialApiResponse:
        self.calls.append(fields)
        return FinancialApiResponse(status=self.status, data=self.data)


@pytest.fixture
def company() -> CompanyRef:
    return CompanyRef(company_id="company-1", company_name="테스트로보틱스")


def make_agent(dart: StubClient, fsc: StubClient, kind: StubClient) -> FinancialAgent:
    normalizer = FinancialNormalizer()
    collector = FinancialCollector(dart, fsc, kind, normalizer=normalizer)
    return FinancialAgent(collector, normalizer)


def test_case_a_dart_complete_skips_fallback_sources(company: CompanyRef) -> None:
    dart = StubClient(
        "dart",
        {
            "revenue": "1,000",
            "operating_income": 100,
            "net_income": 80,
            "total_assets": 2_000,
            "total_liabilities": 900,
            "total_equity": 1_100,
            "current_assets": 800,
            "current_liabilities": 400,
            "cash_and_cash_equivalents": 500,
            "operating_cash_flow": 120,
            "total_funding": 700,
            "unit": "KRW million",
            "as_of": "2025-12-31",
        },
    )
    fsc, kind = StubClient("fsc"), StubClient("kind")

    result = make_agent(dart, fsc, kind).run(company)
    financial_data = result["financial_data"]

    assert financial_data.status == "available"
    assert financial_data.revenue == 1000
    assert financial_data.cash_and_cash_equivalents == 500
    assert financial_data.as_of == "2025-12-31"
    assert set(financial_data.model_dump()) == {
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
        "evidence_ids",
        "missing_facts",
        "as_of",
        "status",
    }
    assert len(dart.calls) == 1
    assert fsc.calls == []
    assert kind.calls == []


def test_case_b_only_missing_fields_are_filled_in_priority_order(company: CompanyRef) -> None:
    dart = StubClient(
        "dart",
        {"revenue": 1_000, "cash_and_cash_equivalents": 300, "as_of": "2025"},
    )
    fsc = StubClient(
        "fsc",
        {
            "revenue": 9_999,
            "operating_profit": 50,
            "net_profit": 30,
            "as_of": "2025",
        },
    )
    kind = StubClient("kind", {"total_asset": 2_000, "cash": 999, "as_of": "2025"})

    result = make_agent(dart, fsc, kind).run(company)
    financial_data = result["financial_data"]

    assert "operating_income" in fsc.calls[0]
    assert "total_assets" in kind.calls[0]
    assert "cash_and_cash_equivalents" not in kind.calls[0]
    assert financial_data.revenue == 1_000
    assert financial_data.operating_income == 50
    assert financial_data.total_assets == 2_000
    assert financial_data.cash_and_cash_equivalents == 300


def test_case_c_no_source_data_is_unavailable_and_records_statuses(company: CompanyRef) -> None:
    dart = StubClient("dart", status=ApiStatus.COMPANY_NOT_FOUND)
    fsc = StubClient("fsc", status=ApiStatus.FINANCIAL_NOT_FOUND)
    kind = StubClient("kind", status=ApiStatus.FINANCIAL_NOT_FOUND)

    result = make_agent(dart, fsc, kind).run(company)
    financial_data = result["financial_data"]

    assert financial_data.status == "unavailable"
    assert financial_data.missing_facts == [
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
    ]
    assert financial_data.evidence_ids == []


def test_api_exception_is_recorded_and_fallback_continues(company: CompanyRef) -> None:
    class BrokenClient(StubClient):
        def fetch(self, company: CompanyRef, fields: list[str]) -> FinancialApiResponse:
            raise RuntimeError("temporary provider failure")

    dart = BrokenClient("dart")
    fsc = StubClient("fsc", {"revenue": 100})
    kind = StubClient("kind", status=ApiStatus.FINANCIAL_NOT_FOUND)

    result = make_agent(dart, fsc, kind).run(company)

    assert dart.calls == []
    assert result["financial_data"].revenue == 100


def test_runway_requires_cash_and_positive_monthly_burn() -> None:
    financials = FinancialData(
        cash_and_cash_equivalents=FinancialValue(value=120, source="dart")
    )
    calculator = FinancialCalculator()

    unknown = calculator.calculate(financials)
    actual = calculator.calculate(financials, monthly_cash_burn=10)
    proxy = calculator.calculate(financials, monthly_cash_burn=20, burn_is_proxy=True)

    assert unknown.runway_months is None
    assert unknown.runway_status == "unavailable"
    assert actual.runway_months == 12
    assert actual.runway_status == "actual"
    assert proxy.runway_months == 6
    assert proxy.runway_status == "proxy"


def test_langgraph_entry_point_accepts_company_mapping(company: CompanyRef) -> None:
    empty = StubClient("dart", status=ApiStatus.FINANCIAL_NOT_FOUND)
    agent = make_agent(empty, StubClient("fsc", status=ApiStatus.FINANCIAL_NOT_FOUND), StubClient("kind", status=ApiStatus.FINANCIAL_NOT_FOUND))

    result = financial_agent({"current_company": company.model_dump()}, agent=agent)

    assert result["financial_data"].status == "unavailable"


def test_public_library_functions_return_json_ready_single_and_batch_results() -> None:
    complete = StubClient(
        "dart",
        {field: 100 for field in FinancialCollector.FIELDS} | {"as_of": "2025-12-31"},
    )
    agent = make_agent(complete, StubClient("fsc"), StubClient("kind"))

    single = get_financial_data("기업A", agent=agent)
    batch = get_financial_data_batch(
        ["기업A", CompanyRef(company_id="company-b", company_name="기업B")],
        agent=agent,
    )

    assert single["revenue"] == 100
    assert single["status"] == "available"
    assert batch["기업A"]["as_of"] == "2025-12-31"
    assert batch["company-b"]["total_funding"] == 100


def test_margins_are_not_calculated_across_different_periods() -> None:
    financials = FinancialData(
        revenue=FinancialValue(value=100, source="dart", as_of="2026-06-30"),
        operating_income=FinancialValue(value=10, source="fsc", as_of="2025-12-31"),
        net_income=FinancialValue(value=8, source="fsc", as_of="2025-12-31"),
    )

    metrics = FinancialCalculator().calculate(financials)

    assert metrics.operating_margin is None
    assert metrics.net_margin is None
