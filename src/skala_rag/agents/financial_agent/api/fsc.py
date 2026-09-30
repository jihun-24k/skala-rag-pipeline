"""Financial Services Commission corporate-finance API client."""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import unquote

import httpx

from ..models.schemas import ApiStatus, CompanyRef, FinancialApiResponse


class FscClient:
    source = "fsc"
    SERVICE_PATH = "/1160100/service/GetFinaStatInfoService_V2"

    SUMMARY_FIELDS = {
        "revenue": ("enpSaleAmt", "saleAmt", "revenue"),
        "operating_income": ("enpBzopPft", "bzopPft", "operatingIncome"),
        "net_income": ("enpCrtmNpf", "crtmNpf", "netIncome"),
        "total_assets": ("enpTastAmt", "tastAmt", "totalAssets"),
        "total_liabilities": ("enpTdbtAmt", "tdbtAmt", "totalLiabilities"),
        "total_equity": ("enpTcptAmt", "tcptAmt", "totalEquity"),
        "cash_and_cash_equivalents": ("cashAndCashEquivalents", "cashEqvlAmt", "cash"),
    }
    BALANCE_SHEET_ACCOUNTS = {
        "total_assets": {
            "ids": {"ifrs-full_Assets", "ifrs_Assets"},
            "names": {"자산총계"},
        },
        "total_liabilities": {
            "ids": {"ifrs-full_Liabilities", "ifrs_Liabilities"},
            "names": {"부채총계"},
        },
        "total_equity": {
            "ids": {"ifrs-full_Equity", "ifrs_Equity"},
            "names": {"자본총계"},
        },
        "current_assets": {
            "ids": {"ifrs-full_CurrentAssets", "ifrs_CurrentAssets"},
            "names": {"유동자산"},
        },
        "current_liabilities": {
            "ids": {"ifrs-full_CurrentLiabilities", "ifrs_CurrentLiabilities"},
            "names": {"유동부채"},
        },
        "cash_and_cash_equivalents": {
            "ids": {
                "ifrs-full_CashAndCashEquivalents",
                "ifrs_CashAndCashEquivalents",
                "dart_CashAndCashEquivalents",
            },
            "names": {"현금및현금성자산", "현금 및 현금성자산"},
        },
    }
    INCOME_STATEMENT_ACCOUNTS = {
        "revenue": {
            "ids": {
                "ifrs-full_Revenue",
                "ifrs_Revenue",
                "ifrs-full_RevenueFromContractsWithCustomers",
            },
            "names": {"매출액", "수익(매출액)", "영업수익"},
        },
        "operating_income": {
            "ids": {"dart_OperatingIncomeLoss"},
            "names": {"영업이익", "영업이익(손실)", "영업손익"},
        },
        "net_income": {
            "ids": {"ifrs-full_ProfitLoss", "ifrs_ProfitLoss"},
            "names": {"당기순이익", "당기순이익(손실)", "당기순손익"},
        },
    }

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://apis.data.go.kr",
        *,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = unquote(api_key) if api_key else None
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)

    def find_company(self, company: CompanyRef) -> FinancialApiResponse:
        if not self.api_key:
            return self._not_configured("find_company")
        if not company.corporation_number:
            return FinancialApiResponse(
                status=ApiStatus.COMPANY_NOT_FOUND,
                error="FSC lookup requires corporation_number (법인등록번호)",
            )
        return FinancialApiResponse(
            status=ApiStatus.AVAILABLE,
            data={"corporation_number": company.corporation_number},
        )

    def get_financial_statements(self, company: CompanyRef) -> FinancialApiResponse:
        found = self.find_company(company)
        if found.status != ApiStatus.AVAILABLE:
            return found

        current_year = date.today().year
        last_error: str | None = None
        for business_year in range(current_year, current_year - 6, -1):
            try:
                payload = self._get_json(
                    "getSummFinaStat_V2",
                    crno=company.corporation_number,
                    bizYear=str(business_year),
                )
            except (httpx.HTTPError, ValueError) as exc:
                return self._api_error(exc)

            header, items = self._unwrap(payload)
            result_code = str(header.get("resultCode") or header.get("resultCd") or "")
            if result_code and result_code not in {"00", "0", "NORMAL_CODE"}:
                last_error = str(header.get("resultMsg") or header.get("resultMessage") or result_code)
                continue
            if not items:
                continue

            item = self._select_item(items)
            data = self._normalize_summary(item)
            as_of = str(item.get("basDt") or item.get("stlmDt") or f"{business_year}1231")
            as_of = self._format_date(as_of)
            scope = self._statement_scope(item)
            for value in data.values():
                value["as_of"] = as_of
                value["unit"] = item.get("curCd") or "KRW"
                value["report_type"] = "annual"
                value["statement_scope"] = scope

            income_statement = self.get_income_statement(company, business_year)
            balance_sheet = self.get_balance_sheet(company, business_year)
            self._merge_detail(data, income_statement)
            self._merge_detail(data, balance_sheet)
            if data:
                return FinancialApiResponse(
                    status=ApiStatus.AVAILABLE,
                    data=data,
                    metadata={
                        "business_year": str(business_year),
                        "period_end": as_of,
                        "corporation_number": company.corporation_number,
                        "income_statement_status": income_statement.status.value,
                        "income_statement_fields": list(income_statement.data),
                        "income_statement_error": income_statement.error,
                        "balance_sheet_status": balance_sheet.status.value,
                        "balance_sheet_fields": list(balance_sheet.data),
                        "balance_sheet_error": balance_sheet.error,
                    },
                )

        return FinancialApiResponse(
            status=ApiStatus.FINANCIAL_NOT_FOUND,
            error=last_error,
            metadata={"corporation_number": company.corporation_number},
        )

    def get_balance_sheet(
        self,
        company: CompanyRef,
        business_year: int | str,
    ) -> FinancialApiResponse:
        """Fetch detailed balance-sheet rows for the requested business year."""
        found = self.find_company(company)
        if found.status != ApiStatus.AVAILABLE:
            return found
        try:
            payload = self._get_json(
                "getBs_V2",
                crno=company.corporation_number,
                bizYear=str(business_year),
            )
        except (httpx.HTTPError, ValueError) as exc:
            return self._api_error(exc)

        header, items = self._unwrap(payload)
        result_code = str(header.get("resultCode") or header.get("resultCd") or "")
        if result_code and result_code not in {"00", "0", "NORMAL_CODE"}:
            return FinancialApiResponse(
                status=ApiStatus.API_ERROR,
                error=str(header.get("resultMsg") or header.get("resultMessage") or result_code),
            )
        if not items:
            return FinancialApiResponse(status=ApiStatus.FINANCIAL_NOT_FOUND)

        scoped_items = self._preferred_scope_rows(items)
        data: dict[str, dict[str, Any]] = {}
        for field, account in self.BALANCE_SHEET_ACCOUNTS.items():
            row = next(
                (
                    item
                    for item in scoped_items
                    if item.get("acitId") in account["ids"]
                    or self._clean_account_name(item.get("acitNm"))
                    in {self._clean_account_name(name) for name in account["names"]}
                ),
                None,
            )
            if row is None:
                continue
            value = row.get("crtmAcitAmt") or row.get("thqrAcitAmt")
            if value in (None, "", "-"):
                continue
            as_of = self._format_date(str(row.get("basDt") or f"{business_year}1231"))
            data[field] = {
                "value": value,
                "previous_value": row.get("pvtrAcitAmt"),
                "as_of": as_of,
                "previous_as_of": f"{int(str(business_year)) - 1}-12-31",
                "unit": row.get("curCd") or "KRW",
                "report_type": "annual" if as_of.endswith("12-31") else None,
                "statement_scope": self._statement_scope(row),
            }
        if not data:
            return FinancialApiResponse(
                status=ApiStatus.FINANCIAL_NOT_FOUND,
                metadata={"available_accounts": [item.get("acitNm") for item in scoped_items]},
            )
        return FinancialApiResponse(
            status=ApiStatus.AVAILABLE,
            data=data,
            metadata={
                "business_year": str(business_year),
                "available_accounts": [item.get("acitNm") for item in scoped_items],
            },
        )

    def get_income_statement(
        self,
        company: CompanyRef,
        business_year: int | str,
    ) -> FinancialApiResponse:
        """Fetch detailed income-statement rows for the requested business year."""
        found = self.find_company(company)
        if found.status != ApiStatus.AVAILABLE:
            return found
        try:
            payload = self._get_json(
                "getIncoStat_V2",
                crno=company.corporation_number,
                bizYear=str(business_year),
            )
        except (httpx.HTTPError, ValueError) as exc:
            return self._api_error(exc)

        header, items = self._unwrap(payload)
        result_code = str(header.get("resultCode") or header.get("resultCd") or "")
        if result_code and result_code not in {"00", "0", "NORMAL_CODE"}:
            return FinancialApiResponse(
                status=ApiStatus.API_ERROR,
                error=str(header.get("resultMsg") or header.get("resultMessage") or result_code),
            )
        if not items:
            return FinancialApiResponse(status=ApiStatus.FINANCIAL_NOT_FOUND)

        scoped_items = self._preferred_scope_rows(items)
        data: dict[str, dict[str, Any]] = {}
        for field, account in self.INCOME_STATEMENT_ACCOUNTS.items():
            cleaned_names = {self._clean_account_name(name) for name in account["names"]}
            row = next(
                (
                    item
                    for item in scoped_items
                    if item.get("acitId") in account["ids"]
                    or self._clean_account_name(item.get("acitNm")) in cleaned_names
                ),
                None,
            )
            if row is None:
                continue
            value = self._first_amount(row, "crtmAcitAmt", "thqrAcitAmt")
            if value is None:
                continue
            as_of = self._format_date(str(row.get("basDt") or f"{business_year}1231"))
            data[field] = {
                "value": value,
                "previous_value": self._first_amount(row, "pvtrAcitAmt", "lsqtAcitAmt"),
                "as_of": as_of,
                "previous_as_of": f"{int(str(business_year)) - 1}-12-31",
                "unit": row.get("curCd") or "KRW",
                "report_type": "annual" if as_of.endswith("12-31") else None,
                "statement_scope": self._statement_scope(row),
            }
        if not data:
            return FinancialApiResponse(
                status=ApiStatus.FINANCIAL_NOT_FOUND,
                metadata={"available_accounts": [item.get("acitNm") for item in scoped_items]},
            )
        return FinancialApiResponse(
            status=ApiStatus.AVAILABLE,
            data=data,
            metadata={
                "business_year": str(business_year),
                "available_accounts": [item.get("acitNm") for item in scoped_items],
            },
        )

    def fetch(self, company: CompanyRef, fields: list[str]) -> FinancialApiResponse:
        response = self.get_financial_statements(company)
        if response.status == ApiStatus.AVAILABLE:
            response.data = {key: value for key, value in response.data.items() if key in fields}
            if not response.data:
                response.status = ApiStatus.FINANCIAL_NOT_FOUND
        return response

    def _get_json(self, operation: str, **params: Any) -> dict[str, Any]:
        response = self.client.get(
            f"{self.base_url}{self.SERVICE_PATH}/{operation}",
            params={
                "serviceKey": self.api_key,
                "resultType": "json",
                "pageNo": 1,
                "numOfRows": 100,
                **params,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("FSC returned a non-object JSON response")
        return payload

    @staticmethod
    def _unwrap(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        response = payload.get("response", payload)
        header = response.get("header", {}) if isinstance(response, dict) else {}
        body = response.get("body", {}) if isinstance(response, dict) else {}
        items: Any = body.get("items", []) if isinstance(body, dict) else []
        if isinstance(items, dict):
            items = items.get("item", items)
        if isinstance(items, dict):
            items = [items]
        return header, [item for item in (items or []) if isinstance(item, dict)]

    @staticmethod
    def _select_item(items: list[dict[str, Any]]) -> dict[str, Any]:
        # Consolidated financial statements are preferred where the provider
        # exposes a financial-statement classification name/code.
        consolidated = [item for item in items if "연결" in str(item.get("fnclDcdNm") or "")]
        candidates = consolidated or items
        return max(candidates, key=lambda item: str(item.get("basDt") or ""))

    @staticmethod
    def _preferred_scope_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        consolidated = [item for item in items if "연결" in str(item.get("fnclDcdNm") or "")]
        return consolidated or items

    @staticmethod
    def _statement_scope(item: dict[str, Any]) -> str:
        return "consolidated" if "연결" in str(item.get("fnclDcdNm") or "") else "separate"

    @staticmethod
    def _clean_account_name(value: Any) -> str:
        return "".join(str(value or "").split())

    @staticmethod
    def _first_amount(item: dict[str, Any], *keys: str) -> Any | None:
        for key in keys:
            value = item.get(key)
            if value not in (None, "", "-"):
                return value
        return None

    @staticmethod
    def _merge_detail(data: dict[str, Any], detail: FinancialApiResponse) -> None:
        if detail.status != ApiStatus.AVAILABLE:
            return
        for field, detailed_value in detail.data.items():
            if field not in data:
                data[field] = detailed_value
                continue
            for key, value in detailed_value.items():
                if data[field].get(key) in (None, "") and value not in (None, ""):
                    data[field][key] = value

    @classmethod
    def _normalize_summary(cls, item: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for field, aliases in cls.SUMMARY_FIELDS.items():
            for alias in aliases:
                value = item.get(alias)
                if value not in (None, "", "-"):
                    result[field] = {"value": value}
                    break
        return result

    @staticmethod
    def _format_date(value: str) -> str:
        digits = "".join(character for character in value if character.isdigit())
        if len(digits) == 8:
            return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
        return value

    @staticmethod
    def _not_configured(method: str) -> FinancialApiResponse:
        return FinancialApiResponse(
            status=ApiStatus.NOT_CONFIGURED,
            error=f"FSC {method} requires FSC_API_KEY",
        )

    @staticmethod
    def _api_error(exc: Exception) -> FinancialApiResponse:
        if isinstance(exc, httpx.HTTPStatusError):
            request = exc.request
            error = (
                f"FSC HTTP {exc.response.status_code}: {request.method} {request.url.path}; "
                "verify FSC_API_KEY and data.go.kr service authorization"
            )
        elif isinstance(exc, httpx.RequestError):
            error = f"FSC request failed: {exc.__class__.__name__}"
        else:
            error = str(exc)
        return FinancialApiResponse(status=ApiStatus.API_ERROR, error=error)
