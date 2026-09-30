"""Synchronous OpenDART client used by the financial collector."""

from __future__ import annotations

import calendar
import io
import re
import zipfile
from datetime import date
from typing import Any, Iterable
from xml.etree import ElementTree

import httpx

from ..models.schemas import ApiStatus, CompanyRef, FinancialApiResponse


class DartClient:
    source = "dart"

    REPORT_CODES = {
        "first_quarter": "11013",
        "half_year": "11012",
        "third_quarter": "11014",
        "annual": "11011",
    }
    ACCOUNT_IDS = {
        "revenue": {
            "ifrs-full_Revenue",
            "ifrs-full_RevenueFromContractsWithCustomers",
            "dart_Revenue",
        },
        "operating_income": {"dart_OperatingIncomeLoss"},
        "net_income": {"ifrs-full_ProfitLoss"},
        "total_assets": {"ifrs-full_Assets"},
        "total_liabilities": {"ifrs-full_Liabilities"},
        "total_equity": {"ifrs-full_Equity"},
        "current_assets": {"ifrs-full_CurrentAssets"},
        "current_liabilities": {"ifrs-full_CurrentLiabilities"},
        "cash_and_cash_equivalents": {
            "ifrs-full_CashAndCashEquivalents",
            "dart_CashAndCashEquivalents",
        },
        "operating_cash_flow": {
            "ifrs-full_CashFlowsFromUsedInOperatingActivities",
            "dart_CashFlowsFromUsedInOperatingActivities",
        },
    }
    ACCOUNT_NAMES = {
        "revenue": ("매출액", "영업수익", "수익(매출액)"),
        "operating_income": ("영업이익", "영업이익(손실)", "영업손익"),
        "net_income": ("당기순이익", "당기순이익(손실)", "당기순손익"),
        "total_assets": ("자산총계",),
        "total_liabilities": ("부채총계",),
        "total_equity": ("자본총계",),
        "current_assets": ("유동자산",),
        "current_liabilities": ("유동부채",),
        "cash_and_cash_equivalents": ("현금및현금성자산", "현금 및 현금성자산"),
        "operating_cash_flow": (
            "영업활동현금흐름",
            "영업활동으로인한현금흐름",
            "영업활동으로 인한 현금흐름",
        ),
    }

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://opendart.fss.or.kr/api",
        *,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)
        self._companies: list[dict[str, str]] | None = None

    def find_company(self, company_name: str) -> FinancialApiResponse:
        if not self.api_key:
            return self._not_configured("find_company")
        try:
            companies = self._load_company_codes()
        except (httpx.HTTPError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            return self._api_error(exc)

        exact = [item for item in companies if item["corp_name"] == company_name.strip()]
        candidates = exact or [
            item
            for item in companies
            if self._normalize_company_name(item["corp_name"])
            == self._normalize_company_name(company_name)
        ]
        if not candidates:
            return FinancialApiResponse(status=ApiStatus.COMPANY_NOT_FOUND)

        candidates.sort(key=lambda item: (not bool(item.get("stock_code")), item["corp_code"]))
        selected = candidates[0]
        return FinancialApiResponse(
            status=ApiStatus.AVAILABLE,
            data=selected,
            metadata={"candidate_count": len(candidates)},
        )

    def get_financial_statements(
        self,
        corp_code: str,
        report: dict[str, str] | None = None,
    ) -> FinancialApiResponse:
        if not self.api_key:
            return self._not_configured("get_financial_statements")
        if report is None:
            filings = self.get_filings(corp_code)
            if filings.status != ApiStatus.AVAILABLE:
                return filings
            report = self._select_latest_report(filings.data.get("filings", []))
        if not report:
            return FinancialApiResponse(status=ApiStatus.FINANCIAL_NOT_FOUND)

        last_error: str | None = None
        for fs_div, scope in (("CFS", "consolidated"), ("OFS", "separate")):
            try:
                payload = self._get_json(
                    "fnlttSinglAcntAll.json",
                    corp_code=corp_code,
                    bsns_year=report["business_year"],
                    reprt_code=report["report_code"],
                    fs_div=fs_div,
                )
            except (httpx.HTTPError, ValueError) as exc:
                return self._api_error(exc)
            if payload.get("status") == "013":
                last_error = payload.get("message")
                continue
            error = self._dart_payload_error(payload)
            if error is not None:
                return error

            rows = payload.get("list") or []
            data = self._extract_financials(rows, report, scope)
            if data:
                return FinancialApiResponse(
                    status=ApiStatus.AVAILABLE,
                    data=data,
                    metadata={
                        **report,
                        "statement_scope": scope,
                        "dart_corp_code": corp_code,
                    },
                )

        return FinancialApiResponse(
            status=ApiStatus.FINANCIAL_NOT_FOUND,
            error=last_error,
            metadata={**report, "dart_corp_code": corp_code},
        )

    def get_filings(self, corp_code: str, as_of: date | None = None) -> FinancialApiResponse:
        if not self.api_key:
            return self._not_configured("get_filings")
        as_of = as_of or date.today()
        try:
            payload = self._get_json(
                "list.json",
                corp_code=corp_code,
                bgn_de=f"{as_of.year - 3}0101",
                end_de=as_of.strftime("%Y%m%d"),
                last_reprt_at="Y",
                pblntf_ty="A",
                sort="date",
                sort_mth="desc",
                page_count=100,
            )
        except (httpx.HTTPError, ValueError) as exc:
            return self._api_error(exc)
        if payload.get("status") == "013":
            return FinancialApiResponse(status=ApiStatus.FINANCIAL_NOT_FOUND)
        error = self._dart_payload_error(payload)
        if error is not None:
            return error

        filings = []
        for item in payload.get("list") or []:
            report = self._parse_report(item)
            if report is not None:
                filings.append(report)
        if not filings:
            return FinancialApiResponse(status=ApiStatus.FINANCIAL_NOT_FOUND)
        filings.sort(key=lambda item: (item["period_end"], item["receipt_date"]), reverse=True)
        return FinancialApiResponse(status=ApiStatus.AVAILABLE, data={"filings": filings})

    def download_document(self, receipt_no: str) -> FinancialApiResponse:
        if not self.api_key:
            return self._not_configured("download_document")
        try:
            response = self.client.get(
                f"{self.base_url}/document.xml",
                params={"crtfc_key": self.api_key, "rcept_no": receipt_no},
            )
            response.raise_for_status()
            return FinancialApiResponse(
                status=ApiStatus.AVAILABLE,
                data={"content": response.content, "receipt_no": receipt_no},
            )
        except httpx.HTTPError as exc:
            return self._api_error(exc)

    def fetch(self, company: CompanyRef, fields: list[str]) -> FinancialApiResponse:
        """Resolve the company and retrieve its newest final periodic statement."""
        corp_code = company.dart_corp_code
        if not corp_code:
            found = self.find_company(company.company_name)
            if found.status != ApiStatus.AVAILABLE:
                return found
            corp_code = str(found.data.get("corp_code") or "")
            company.dart_corp_code = corp_code or None
            stock_code = str(found.data.get("stock_code") or "").strip()
            if stock_code:
                company.listed = True
        if not corp_code:
            return FinancialApiResponse(status=ApiStatus.COMPANY_NOT_FOUND)

        self._enrich_company(company, corp_code)
        filings = self.get_filings(corp_code)
        if filings.status != ApiStatus.AVAILABLE:
            return filings
        last_not_found: FinancialApiResponse | None = None
        for report in filings.data.get("filings", []):
            response = self.get_financial_statements(corp_code, report=report)
            if response.status == ApiStatus.AVAILABLE:
                return response
            if response.status != ApiStatus.FINANCIAL_NOT_FOUND:
                return response
            last_not_found = response
        return last_not_found or FinancialApiResponse(status=ApiStatus.FINANCIAL_NOT_FOUND)

    def _load_company_codes(self) -> list[dict[str, str]]:
        if self._companies is not None:
            return self._companies
        response = self.client.get(
            f"{self.base_url}/corpCode.xml",
            params={"crtfc_key": self.api_key},
        )
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            xml_name = next(name for name in archive.namelist() if name.lower().endswith(".xml"))
            root = ElementTree.fromstring(archive.read(xml_name))
        self._companies = [
            {
                "corp_code": node.findtext("corp_code", "").strip(),
                "corp_name": node.findtext("corp_name", "").strip(),
                "stock_code": node.findtext("stock_code", "").strip(),
                "modify_date": node.findtext("modify_date", "").strip(),
            }
            for node in root.findall("list")
        ]
        return self._companies

    def _enrich_company(self, company: CompanyRef, corp_code: str) -> None:
        try:
            payload = self._get_json("company.json", corp_code=corp_code)
        except (httpx.HTTPError, ValueError):
            return
        if payload.get("status") != "000":
            return
        company.corporation_number = company.corporation_number or payload.get("jurir_no") or None
        company.business_number = company.business_number or payload.get("bizr_no") or None

    def _get_json(self, endpoint: str, **params: Any) -> dict[str, Any]:
        response = self.client.get(
            f"{self.base_url}/{endpoint}",
            params={"crtfc_key": self.api_key, **params},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("DART returned a non-object JSON response")
        return payload

    @classmethod
    def _parse_report(cls, item: dict[str, Any]) -> dict[str, str] | None:
        name = str(item.get("report_nm") or "")
        period_match = re.search(r"\((\d{4})\.(\d{2})\)", name)
        if "사업보고서" in name:
            report_type = "annual"
        elif "반기보고서" in name:
            report_type = "half_year"
        elif "분기보고서" in name and period_match and period_match.group(2) == "03":
            report_type = "first_quarter"
        elif "분기보고서" in name and period_match and period_match.group(2) == "09":
            report_type = "third_quarter"
        else:
            return None

        if period_match:
            year, month = map(int, period_match.groups())
        else:
            receipt_date = str(item.get("rcept_dt") or "")
            if len(receipt_date) < 4:
                return None
            year = int(receipt_date[:4]) - (1 if report_type == "annual" else 0)
            month = {"annual": 12, "half_year": 6, "first_quarter": 3, "third_quarter": 9}[report_type]
        period_end = date(year, month, calendar.monthrange(year, month)[1]).isoformat()
        return {
            "report_type": report_type,
            "report_code": cls.REPORT_CODES[report_type],
            "business_year": str(year),
            "period_end": period_end,
            "receipt_no": str(item.get("rcept_no") or ""),
            "receipt_date": str(item.get("rcept_dt") or ""),
            "report_name": name,
        }

    @staticmethod
    def _select_latest_report(filings: Iterable[dict[str, str]]) -> dict[str, str] | None:
        return max(filings, key=lambda item: (item["period_end"], item["receipt_date"]), default=None)

    @classmethod
    def _extract_financials(
        cls,
        rows: list[dict[str, Any]],
        report: dict[str, str],
        scope: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        report_type = report["report_type"]
        for field in cls.ACCOUNT_IDS:
            row = cls._best_row(rows, field)
            if row is None:
                continue
            is_flow = field in {
                "revenue",
                "operating_income",
                "net_income",
                "operating_cash_flow",
            }
            cumulative = report_type != "annual" and is_flow
            current_key = "thstrm_add_amount" if cumulative else "thstrm_amount"
            previous_key = "frmtrm_add_amount" if cumulative else "frmtrm_amount"
            current_raw = row.get(current_key) or row.get("thstrm_amount")
            previous_raw = row.get(previous_key) or row.get("frmtrm_amount")
            if cls._parse_amount(current_raw) is None:
                continue
            result[field] = {
                "value": current_raw,
                "previous_value": previous_raw,
                "as_of": report["period_end"],
                "previous_as_of": cls._previous_period(
                    report["period_end"], field=field, report_type=report_type
                ),
                "unit": row.get("currency") or "KRW",
                "report_type": report_type,
                "statement_scope": scope,
                "receipt_no": report["receipt_no"],
            }
        return result

    @classmethod
    def _best_row(cls, rows: list[dict[str, Any]], field: str) -> dict[str, Any] | None:
        if field == "operating_cash_flow":
            expected_statement = {"CF"}
        elif field in {
            "total_assets",
            "total_liabilities",
            "total_equity",
            "current_assets",
            "current_liabilities",
            "cash_and_cash_equivalents",
        }:
            expected_statement = {"BS"}
        else:
            expected_statement = {"IS", "CIS"}
        normalized_names = {cls._clean_account_name(name) for name in cls.ACCOUNT_NAMES[field]}
        candidates = [
            row
            for row in rows
            if row.get("sj_div") in expected_statement
            and (
                row.get("account_id") in cls.ACCOUNT_IDS[field]
                or cls._clean_account_name(row.get("account_nm")) in normalized_names
            )
        ]
        candidates.sort(
            key=lambda row: (
                row.get("account_id") not in cls.ACCOUNT_IDS[field],
                row.get("sj_div") != "IS",
            )
        )
        return candidates[0] if candidates else None

    @staticmethod
    def _parse_amount(value: Any) -> float | None:
        if value is None:
            return None
        text = str(value).strip().replace(",", "")
        if text in {"", "-"}:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _previous_period(value: str, *, field: str, report_type: str) -> str:
        year, month, day = map(int, value.split("-"))
        if field in {
            "total_assets",
            "total_liabilities",
            "total_equity",
            "current_assets",
            "current_liabilities",
            "cash_and_cash_equivalents",
        } and report_type != "annual":
            return date(year - 1, 12, 31).isoformat()
        return date(year - 1, month, min(day, calendar.monthrange(year - 1, month)[1])).isoformat()

    @staticmethod
    def _clean_account_name(value: Any) -> str:
        return re.sub(r"[\s\[\]]", "", str(value or ""))

    @staticmethod
    def _normalize_company_name(value: str) -> str:
        normalized = re.sub(r"\s+", "", value)
        normalized = normalized.replace("주식회사", "").replace("(주)", "").replace("㈜", "")
        return normalized.casefold()

    @staticmethod
    def _dart_payload_error(payload: dict[str, Any]) -> FinancialApiResponse | None:
        status = payload.get("status")
        if status == "000":
            return None
        if status == "013":
            return FinancialApiResponse(status=ApiStatus.FINANCIAL_NOT_FOUND)
        return FinancialApiResponse(
            status=ApiStatus.API_ERROR,
            error=f"DART {status}: {payload.get('message', 'unknown error')}",
        )

    @staticmethod
    def _api_error(exc: Exception) -> FinancialApiResponse:
        if isinstance(exc, httpx.HTTPStatusError):
            request = exc.request
            error = f"DART HTTP {exc.response.status_code}: {request.method} {request.url.path}"
        elif isinstance(exc, httpx.RequestError):
            error = f"DART request failed: {exc.__class__.__name__}"
        else:
            error = str(exc)
        return FinancialApiResponse(status=ApiStatus.API_ERROR, error=error)

    @staticmethod
    def _not_configured(method: str) -> FinancialApiResponse:
        return FinancialApiResponse(
            status=ApiStatus.NOT_CONFIGURED,
            error=f"DART {method} requires DART_API_KEY",
        )
