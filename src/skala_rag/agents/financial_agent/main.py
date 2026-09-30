"""Standalone CLI for explicit mock or live financial-agent runs."""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

from pydantic import BaseModel

from .agent.financial_agent import FinancialAgent, build_default_agent
from .models.schemas import ApiStatus, CompanyRef, FinancialApiResponse
from .service import FinancialCollector, FinancialNormalizer


class MockClient:
    def __init__(self, source: str, data: dict[str, object]) -> None:
        self.source = source
        self.data = data

    def fetch(self, company: CompanyRef, fields: list[str]) -> FinancialApiResponse:
        selected = {key: value for key, value in self.data.items() if key in fields}
        selected.update({key: self.data[key] for key in ("unit", "as_of") if key in self.data})
        has_financial_value = any(key in selected for key in fields)
        status = ApiStatus.AVAILABLE if has_financial_value else ApiStatus.FINANCIAL_NOT_FOUND
        return FinancialApiResponse(status=status, data=selected)


def build_mock_agent() -> FinancialAgent:
    normalizer = FinancialNormalizer()
    collector = FinancialCollector(
        MockClient(
            "dart",
            {
                "revenue": {"value": 3_200_000_000, "previous_value": 2_500_000_000},
                "unit": "KRW",
                "as_of": "2025-12-31",
            },
        ),
        MockClient(
            "fsc",
            {
                "operating_income": -500_000_000,
                "net_income": -650_000_000,
                "unit": "KRW",
                "as_of": "2025-12-31",
            },
        ),
        MockClient(
            "kind",
            {
                "total_assets": {"value": 5_000_000_000, "previous_value": 4_200_000_000},
                "total_liabilities": 2_400_000_000,
                "total_equity": 2_600_000_000,
                "current_assets": 2_000_000_000,
                "current_liabilities": 900_000_000,
                "cash_and_cash_equivalents": 1_100_000_000,
                "operating_cash_flow": -350_000_000,
                "total_funding": 4_500_000_000,
                "unit": "KRW",
                "as_of": "2025-12-31",
            },
        ),
        normalizer=normalizer,
    )
    return FinancialAgent(
        collector,
        normalizer,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the financial agent")
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--company-name", default="로브로스")
    parser.add_argument("--company-id")
    parser.add_argument("--dart-corp-code")
    parser.add_argument("--corporation-number")
    parser.add_argument("--business-number")
    return parser.parse_args()


def _default_company_id(name: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z가-힣]+", "-", name).strip("-").lower()
    return normalized or "company"


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def main() -> None:
    args = parse_args()
    company = CompanyRef(
        company_id=args.company_id or _default_company_id(args.company_name),
        company_name=args.company_name,
        dart_corp_code=args.dart_corp_code,
        corporation_number=args.corporation_number,
        business_number=args.business_number,
    )
    agent = build_mock_agent() if args.mode == "mock" else build_default_agent()
    result = agent.run(company)
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
