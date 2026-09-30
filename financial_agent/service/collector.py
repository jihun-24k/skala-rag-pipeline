"""Ordered DART -> FSC -> KIND financial collection."""

from __future__ import annotations

from typing import Any, Protocol

from ..models.schemas import (
    ApiStatus,
    CompanyRef,
    FinancialApiResponse,
    FinancialCollectionResult,
    FinancialData,
    SourceCollectionReport,
)
from .normalizer import FinancialNormalizer


class FinancialSourceClient(Protocol):
    source: str

    def fetch(self, company: CompanyRef, fields: list[str]) -> FinancialApiResponse: ...


class FinancialCollector:
    """Fill only missing fields, retaining the provenance of accepted values."""

    FIELDS = [
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

    def __init__(
        self,
        dart_client: FinancialSourceClient,
        fsc_client: FinancialSourceClient,
        kind_client: FinancialSourceClient,
        normalizer: FinancialNormalizer | None = None,
    ) -> None:
        self.sources = (dart_client, fsc_client, kind_client)
        self.normalizer = normalizer or FinancialNormalizer()

    def collect(self, company: CompanyRef) -> FinancialCollectionResult:
        financials = FinancialData()
        reports: list[SourceCollectionReport] = []

        for client in self.sources:
            missing = financials.missing_fields()
            if not missing:
                break
            source = client.source
            try:
                response = client.fetch(company, missing)
                if not isinstance(response, FinancialApiResponse):
                    response = FinancialApiResponse.model_validate(response)
            except Exception as exc:  # isolate one provider so fallback can continue
                response = FinancialApiResponse(status=ApiStatus.API_ERROR, error=str(exc))

            accepted: list[str] = []
            if response.status == ApiStatus.AVAILABLE:
                normalized = self.normalizer.normalize(response.data, source=source, fields=missing)
                for field in missing:
                    candidate = getattr(normalized, field)
                    if candidate is not None and candidate.value is not None:
                        setattr(financials, field, candidate)
                        accepted.append(field)

            reports.append(
                SourceCollectionReport(
                    source=source,
                    status=response.status,
                    requested_fields=missing,
                    accepted_fields=accepted,
                    metadata=response.metadata,
                    error=response.error,
                )
            )

        return FinancialCollectionResult(financials=financials, source_reports=reports)
