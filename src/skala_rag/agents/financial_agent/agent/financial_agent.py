"""D-agent entry point for standalone use or a parent workflow."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Mapping

from ..api import DartClient, FscClient, KindClient
from ..config import Settings, get_settings
from ..models.schemas import FINANCIAL_FIELDS, CompanyRef, FinancialAgentOutput
from ..service import FinancialCollector, FinancialNormalizer


class FinancialAgent:
    """Thin orchestration layer; source and calculation details live elsewhere."""

    def __init__(
        self,
        collector: FinancialCollector,
        normalizer: FinancialNormalizer | None = None,
    ) -> None:
        self.collector = collector
        self.normalizer = normalizer or FinancialNormalizer()

    def run(self, company: CompanyRef) -> dict[str, Any]:
        collected = self.collector.collect(company)
        normalized = self.normalizer.normalize(collected.financials)
        missing = normalized.missing_fields()
        populated = len(self.collector.FIELDS) - len(missing)
        status = "unavailable" if populated == 0 else ("available" if not missing else "partial")
        values = {
            field: item.value if (item := getattr(normalized, field)) is not None else None
            for field in FINANCIAL_FIELDS
        }
        evidence_ids = list(
            dict.fromkeys(
                item.receipt_no
                for field in FINANCIAL_FIELDS
                if (item := getattr(normalized, field)) is not None and item.receipt_no
            )
        )
        dates = [
            item.as_of
            for field in FINANCIAL_FIELDS
            if (item := getattr(normalized, field)) is not None and item.as_of
        ]
        financial_data = FinancialAgentOutput(
            **values,
            evidence_ids=evidence_ids,
            missing_facts=missing,
            as_of=max(dates, default=None),
            status=status,
        )
        return {"financial_data": financial_data}


def build_default_agent(settings: Settings | None = None) -> FinancialAgent:
    settings = settings or get_settings()
    reveal = lambda secret: secret.get_secret_value() if secret is not None else None
    normalizer = FinancialNormalizer()
    collector = FinancialCollector(
        DartClient(api_key=reveal(settings.dart_api_key)),
        FscClient(api_key=reveal(settings.fsc_api_key)),
        KindClient(api_key=reveal(settings.kind_api_key)),
        normalizer=normalizer,
    )
    return FinancialAgent(
        collector=collector,
        normalizer=normalizer,
    )


def run_financial_agent(company: CompanyRef, agent: FinancialAgent | None = None) -> dict[str, Any]:
    return (agent or build_default_agent()).run(company)


def get_financial_data(
    company_name: str,
    *,
    company_id: str | None = None,
    business_number: str | None = None,
    corporation_number: str | None = None,
    dart_corp_code: str | None = None,
    agent: FinancialAgent | None = None,
) -> dict[str, Any]:
    """Public convenience API returning JSON-ready financial data for one company."""
    company = CompanyRef(
        company_id=company_id or company_name,
        company_name=company_name,
        business_number=business_number,
        corporation_number=corporation_number,
        dart_corp_code=dart_corp_code,
    )
    result = run_financial_agent(company, agent=agent)["financial_data"]
    return result.model_dump(mode="json")


def get_financial_data_batch(
    companies: Iterable[str | CompanyRef],
    *,
    agent: FinancialAgent | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch multiple companies while reusing clients and the DART company-code cache."""
    shared_agent = agent or build_default_agent()
    results: dict[str, dict[str, Any]] = {}
    for item in companies:
        company = (
            item
            if isinstance(item, CompanyRef)
            else CompanyRef(company_id=item, company_name=item)
        )
        financial_data = shared_agent.run(company)["financial_data"]
        results[company.company_id] = financial_data.model_dump(mode="json")
    return results


def financial_agent(state: Mapping[str, Any], agent: FinancialAgent | None = None) -> dict[str, Any]:
    """LangGraph-compatible node reading ``state['current_company']``."""
    raw_company = state["current_company"]
    company = raw_company if isinstance(raw_company, CompanyRef) else CompanyRef.model_validate(raw_company)
    return run_financial_agent(company, agent=agent)
