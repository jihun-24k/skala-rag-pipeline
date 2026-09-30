"""Deterministic calculations; no LLM calls belong in this module."""

from __future__ import annotations

from ..models.schemas import FinancialData, FinancialMetrics


class FinancialCalculator:
    @staticmethod
    def calculate_growth(current: float | None, previous: float | None) -> float | None:
        if current is None or previous in (None, 0):
            return None
        return (current - previous) / abs(previous)

    @staticmethod
    def calculate_margin(revenue: float | None, profit: float | None) -> float | None:
        if revenue in (None, 0) or profit is None:
            return None
        return profit / revenue

    @staticmethod
    def calculate_runway(cash: float | None, monthly_cash_burn: float | None) -> float | None:
        if cash is None or monthly_cash_burn is None or monthly_cash_burn <= 0:
            return None
        return cash / monthly_cash_burn

    def calculate(
        self,
        financials: FinancialData,
        previous_financials: FinancialData | None = None,
        monthly_cash_burn: float | None = None,
        burn_is_proxy: bool = False,
    ) -> FinancialMetrics:
        get = lambda data, field: (
            getattr(data, field).value if data is not None and getattr(data, field) is not None else None
        )
        revenue = get(financials, "revenue")
        operating_income = get(financials, "operating_income")
        net_income = get(financials, "net_income")
        cash = get(financials, "cash_and_cash_equivalents")
        runway = self.calculate_runway(cash, monthly_cash_burn)

        def previous(field: str) -> float | None:
            if previous_financials is not None:
                return get(previous_financials, field)
            item = getattr(financials, field)
            return item.previous_value if item is not None else None

        def same_period(left: str, right: str) -> bool:
            left_value = getattr(financials, left)
            right_value = getattr(financials, right)
            if left_value is None or right_value is None:
                return False
            return left_value.as_of == right_value.as_of and (
                left_value.report_type is None
                or right_value.report_type is None
                or left_value.report_type == right_value.report_type
            )

        return FinancialMetrics(
            revenue_growth=self.calculate_growth(revenue, previous("revenue")),
            operating_margin=(
                self.calculate_margin(revenue, operating_income)
                if same_period("revenue", "operating_income")
                else None
            ),
            net_margin=(
                self.calculate_margin(revenue, net_income)
                if same_period("revenue", "net_income")
                else None
            ),
            asset_growth=self.calculate_growth(
                get(financials, "total_assets"),
                previous("total_assets"),
            ),
            runway_months=runway,
            runway_status=("proxy" if burn_is_proxy else "actual") if runway is not None else "unavailable",
        )
