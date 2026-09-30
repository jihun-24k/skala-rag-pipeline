"""Rule-based interpretation of normalized financial information."""

from __future__ import annotations

from ..models.schemas import FinancialData, FinancialMetrics


class FinancialAnalyzer:
    def analyze(
        self,
        financials: FinancialData,
        metrics: FinancialMetrics,
    ) -> dict[str, object]:
        missing = financials.missing_fields()
        risk_factors: list[str] = []

        if metrics.operating_margin is not None and metrics.operating_margin < 0:
            risk_factors.append("negative_operating_margin")
        if metrics.net_margin is not None and metrics.net_margin < 0:
            risk_factors.append("negative_net_margin")
        if metrics.runway_months is not None and metrics.runway_months < 12:
            risk_factors.append("runway_under_12_months")

        return {
            "growth_status": self._growth_status(metrics.revenue_growth),
            "profitability_status": self._profitability_status(metrics.operating_margin),
            "capital_need": self._capital_need(metrics),
            "risk_factors": risk_factors,
            "unknown_fields": missing,
        }

    @staticmethod
    def _growth_status(value: float | None) -> str:
        if value is None:
            return "unknown"
        if value > 0:
            return "growing"
        if value < 0:
            return "declining"
        return "flat"

    @staticmethod
    def _profitability_status(value: float | None) -> str:
        if value is None:
            return "unknown"
        return "profitable" if value >= 0 else "loss_making"

    @staticmethod
    def _capital_need(metrics: FinancialMetrics) -> str:
        if metrics.runway_months is None:
            return "unknown"
        if metrics.runway_months < 12:
            return "likely_near_term"
        return "no_near_term_signal"
