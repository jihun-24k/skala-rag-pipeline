"""Normalize provider-specific records into the internal financial schema."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ..models.schemas import FINANCIAL_FIELDS, FinancialData, FinancialSource, FinancialValue


class FinancialNormalizer:
    FIELD_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
        "dart": {
            "revenue": ("revenue", "매출액", "sales", "thstrm_amount"),
            "operating_income": ("operating_income", "영업이익", "영업손익"),
            "net_income": ("net_income", "당기순이익", "당기순손익"),
            "total_assets": ("total_assets", "자산총계", "assets"),
            "total_liabilities": ("total_liabilities", "부채총계", "liabilities"),
            "total_equity": ("total_equity", "자본총계", "equity"),
            "current_assets": ("current_assets", "유동자산"),
            "current_liabilities": ("current_liabilities", "유동부채"),
            "cash_and_cash_equivalents": (
                "cash_and_cash_equivalents",
                "cash",
                "현금및현금성자산",
            ),
            "operating_cash_flow": ("operating_cash_flow", "영업활동현금흐름"),
            "total_funding": ("total_funding", "누적투자금", "총투자금"),
        },
        "fsc": {
            "revenue": ("revenue", "매출액", "sales_amount"),
            "operating_income": ("operating_income", "영업이익", "operating_profit"),
            "net_income": ("net_income", "당기순이익", "net_profit"),
            "total_assets": ("total_assets", "자산총계", "asset_total"),
            "total_liabilities": ("total_liabilities", "부채총계", "liability_total"),
            "total_equity": ("total_equity", "자본총계", "equity_total"),
            "current_assets": ("current_assets", "유동자산"),
            "current_liabilities": ("current_liabilities", "유동부채"),
            "cash_and_cash_equivalents": (
                "cash_and_cash_equivalents",
                "cash",
                "현금및현금성자산",
                "cash_equivalents",
            ),
            "operating_cash_flow": ("operating_cash_flow", "영업활동현금흐름"),
            "total_funding": ("total_funding", "누적투자금", "총투자금"),
        },
        "kind": {
            "revenue": ("revenue", "매출액", "sales"),
            "operating_income": ("operating_income", "영업이익", "operating_profit"),
            "net_income": ("net_income", "당기순이익", "net_profit"),
            "total_assets": ("total_assets", "자산총계", "total_asset"),
            "total_liabilities": ("total_liabilities", "부채총계"),
            "total_equity": ("total_equity", "자본총계"),
            "current_assets": ("current_assets", "유동자산"),
            "current_liabilities": ("current_liabilities", "유동부채"),
            "cash_and_cash_equivalents": (
                "cash_and_cash_equivalents",
                "cash",
                "현금및현금성자산",
                "cash_equivalents",
            ),
            "operating_cash_flow": ("operating_cash_flow", "영업활동현금흐름"),
            "total_funding": ("total_funding", "누적투자금", "총투자금"),
        },
    }

    def normalize(
        self,
        raw: FinancialData | Mapping[str, Any],
        source: FinancialSource | None = None,
        fields: list[str] | None = None,
    ) -> FinancialData:
        if isinstance(raw, FinancialData):
            return raw
        if source is None:
            raise ValueError("source is required when normalizing a raw mapping")

        requested = set(fields or FINANCIAL_FIELDS)
        values: dict[str, FinancialValue | None] = {}
        for canonical in FINANCIAL_FIELDS:
            if canonical not in requested:
                continue
            raw_item = self._find_value(raw, source, canonical)
            values[canonical] = self._to_financial_value(raw_item, raw, source)
        return FinancialData(**values)

    def _find_value(self, raw: Mapping[str, Any], source: str, canonical: str) -> Any:
        for key in self.FIELD_ALIASES[source][canonical]:
            if key in raw:
                return raw[key]
        return None

    def _to_financial_value(
        self,
        item: Any,
        record: Mapping[str, Any],
        source: FinancialSource,
    ) -> FinancialValue | None:
        if item is None:
            return None
        if isinstance(item, FinancialValue):
            return item
        if isinstance(item, Mapping):
            raw_value = item.get("value")
            unit = item.get("unit") or record.get("unit")
            as_of = item.get("as_of") or record.get("as_of")
            previous_value = self.parse_number(item.get("previous_value"))
            previous_as_of = item.get("previous_as_of")
            report_type = item.get("report_type") or record.get("report_type")
            statement_scope = item.get("statement_scope") or record.get("statement_scope")
            receipt_no = item.get("receipt_no") or record.get("receipt_no")
        else:
            raw_value = item
            unit = record.get("unit")
            as_of = record.get("as_of")
            previous_value = None
            previous_as_of = None
            report_type = record.get("report_type")
            statement_scope = record.get("statement_scope")
            receipt_no = record.get("receipt_no")

        value = self.parse_number(raw_value)
        if value is None:
            return None
        return FinancialValue(
            value=value,
            unit=str(unit) if unit is not None else None,
            source=source,
            as_of=str(as_of) if as_of is not None else None,
            previous_value=previous_value,
            previous_as_of=str(previous_as_of) if previous_as_of is not None else None,
            report_type=report_type,
            statement_scope=statement_scope,
            receipt_no=str(receipt_no) if receipt_no is not None else None,
            raw_value=raw_value,
        )

    @staticmethod
    def parse_number(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float, Decimal)):
            return float(value)
        text = str(value).strip().replace(",", "")
        if not text or text in {"-", "N/A", "n/a", "null", "None"}:
            return None
        negative = text.startswith("(") and text.endswith(")")
        if negative:
            text = text[1:-1]
        try:
            parsed = float(Decimal(text))
        except (InvalidOperation, ValueError):
            return None
        return -parsed if negative else parsed
