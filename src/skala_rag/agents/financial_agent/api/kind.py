"""Client for KIND's public disclosure-search and document-viewer pages."""

from __future__ import annotations

from datetime import date
from html import unescape
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from ..models.schemas import ApiStatus, CompanyRef, FinancialApiResponse


class KindClient:
    """Read public KIND HTML endpoints.

    KIND does not expose these searches as a documented JSON OpenAPI. The
    website's public form and viewer endpoints are parsed without an API key.
    ``api_key`` remains accepted for configuration compatibility.
    """

    source = "kind"
    SEARCH_PATH = "/disclosure/searchtotalinfo.do"
    VIEWER_PATH = "/common/disclsviewer.do"
    INVESTMENT_TERMS = (
        "투자",
        "출자",
        "비상장",
        "경영참여",
        "rcps",
        "전환상환우선주",
        "지분",
        "주식",
    )

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://kind.krx.co.kr",
        *,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; financial-agent/1.0)",
            "Referer": f"{self.base_url}{self.SEARCH_PATH}?method=searchTotalInfoMain",
        }

    def find_company(self, company_name: str) -> FinancialApiResponse:
        """Find an exact listed issuer among actual KIND disclosure results."""
        searched = self._search_disclosures(company_name, max_pages=2)
        if searched.status != ApiStatus.AVAILABLE:
            return searched

        target = self._normalize_name(company_name)
        companies: dict[str, dict[str, str]] = {}
        for filing in searched.data.get("filings", []):
            filing_company = filing.get("filing_company") or ""
            if self._normalize_name(filing_company) != target:
                continue
            code = filing.get("kind_company_code") or ""
            companies[code] = {
                "company_name": filing_company,
                "kind_company_code": code,
            }
        if not companies:
            return FinancialApiResponse(
                status=ApiStatus.COMPANY_NOT_FOUND,
                metadata={"searched_filing_count": len(searched.data.get("filings", []))},
            )
        return FinancialApiResponse(
            status=ApiStatus.AVAILABLE,
            data={"companies": list(companies.values())},
            metadata={"search_term": company_name},
        )

    def get_financial_information(self, company: CompanyRef) -> FinancialApiResponse:
        """Check KIND without fabricating values from unstructured disclosures."""
        found = self.find_company(company.company_name)
        if found.status == ApiStatus.API_ERROR:
            return found
        if found.status != ApiStatus.AVAILABLE:
            return FinancialApiResponse(
                status=ApiStatus.FINANCIAL_NOT_FOUND,
                metadata={
                    "company_lookup_status": found.status.value,
                    **found.metadata,
                },
            )
        return FinancialApiResponse(
            status=ApiStatus.FINANCIAL_NOT_FOUND,
            metadata={
                "company_lookup_status": found.status.value,
                "companies": found.data.get("companies", []),
                "reason": "KIND public pages do not provide a stable structured financial API",
            },
        )

    def search_investment_filings(self, target_company_name: str) -> FinancialApiResponse:
        """Search KIND disclosures that mention the target in an investment context."""
        searched = self._search_disclosures(target_company_name)
        if searched.status != ApiStatus.AVAILABLE:
            return searched

        filings = [
            filing
            for filing in searched.data.get("filings", [])
            if self._is_investment_result(filing)
        ]
        if not filings:
            return FinancialApiResponse(
                status=ApiStatus.FINANCIAL_NOT_FOUND,
                metadata={
                    **searched.metadata,
                    "keyword_match_count": len(searched.data.get("filings", [])),
                },
            )
        return FinancialApiResponse(
            status=ApiStatus.AVAILABLE,
            data={"filings": filings},
            metadata={
                **searched.metadata,
                "keyword_match_count": len(searched.data.get("filings", [])),
                "investment_match_count": len(filings),
            },
        )

    def get_document(self, filing_id: str) -> FinancialApiResponse:
        """Resolve a ``receipt_no:document_no`` id and download its original HTML."""
        parts = re.split(r"[:/]", filing_id, maxsplit=1)
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            return FinancialApiResponse(
                status=ApiStatus.API_ERROR,
                error="KIND filing_id must be '<receipt_no>:<document_no>'",
            )
        receipt_no, document_no = parts
        viewer_url = self._viewer_url(receipt_no, document_no)
        try:
            contents = self.client.get(
                f"{self.base_url}{self.VIEWER_PATH}",
                params={"method": "searchContents", "docNo": document_no},
                headers={**self.headers, "Referer": viewer_url},
            )
            contents.raise_for_status()
            document_url = self._extract_document_url(contents.text)
            if not document_url:
                return FinancialApiResponse(
                    status=ApiStatus.FINANCIAL_NOT_FOUND,
                    metadata={"filing_id": filing_id, "viewer_url": viewer_url},
                )
            parsed = urlparse(document_url)
            base_host = urlparse(self.base_url).hostname
            if parsed.hostname != base_host or not parsed.path.startswith("/external/"):
                raise ValueError("KIND returned an unexpected document URL")
            document = self.client.get(document_url, headers=self.headers)
            document.raise_for_status()
        except (httpx.HTTPError, ValueError) as exc:
            return self._api_error(exc)

        return FinancialApiResponse(
            status=ApiStatus.AVAILABLE,
            data={
                "filing_id": filing_id,
                "receipt_no": receipt_no,
                "document_no": document_no,
                "viewer_url": viewer_url,
                "document_url": document_url,
                "content_type": document.headers.get("content-type"),
                "content_html": document.text,
                "content_text": self._text(document.text),
            },
        )

    def fetch(self, company: CompanyRef, fields: list[str]) -> FinancialApiResponse:
        return self.get_financial_information(company)

    def _search_disclosures(
        self,
        keyword: str,
        *,
        max_pages: int = 10,
        page_size: int = 100,
    ) -> FinancialApiResponse:
        if not keyword.strip():
            return FinancialApiResponse(status=ApiStatus.COMPANY_NOT_FOUND)

        today = date.today()
        form: dict[str, Any] = {
            "method": "searchTotalInfoSub",
            "forward": "searchtotalinfo_detail",
            "searchCodeType": "",
            "searchCorpName": keyword,
            "repIsuSrtCd": "",
            "isurCd": "",
            "fdName": "all_disclosure_idx",
            "currentPageSize": page_size,
            "scn": "disclosure",
            "repIsuCd": "",
            "srchFd": "1",
            "kwd": keyword,
        }
        filings: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            # KIND effectively limits broad date ranges, so query each year to
            # avoid silently returning only the current year's disclosures.
            for year in range(today.year, today.year - 6, -1):
                date_to = today.isoformat() if year == today.year else f"{year}-12-31"
                for page in range(1, max_pages + 1):
                    response = self.client.post(
                        f"{self.base_url}{self.SEARCH_PATH}",
                        data={
                            **form,
                            "pageIndex": page,
                            "fromData": f"{year}-01-01",
                            "toData": date_to,
                        },
                        headers=self.headers,
                    )
                    response.raise_for_status()
                    page_filings = self._parse_search_results(response.text)
                    for filing in page_filings:
                        if filing["filing_id"] not in seen:
                            filings.append(filing)
                            seen.add(filing["filing_id"])
                    if len(page_filings) < page_size:
                        break
        except httpx.HTTPError as exc:
            return self._api_error(exc)

        if not filings:
            return FinancialApiResponse(
                status=ApiStatus.FINANCIAL_NOT_FOUND,
                metadata={"search_term": keyword, "search_url": f"{self.base_url}{self.SEARCH_PATH}"},
            )
        return FinancialApiResponse(
            status=ApiStatus.AVAILABLE,
            data={"filings": filings},
            metadata={
                "search_term": keyword,
                "search_url": f"{self.base_url}{self.SEARCH_PATH}",
                "date_from": f"{today.year - 5}-01-01",
                "date_to": today.isoformat(),
                "result_count": len(filings),
            },
        )

    def _parse_search_results(self, source: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        blocks = re.findall(
            r"<dt\b[^>]*class=[\"'][^\"']*\bimg\b[^\"']*[\"'][^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>",
            source,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for heading, detail in blocks:
            company_match = re.search(
                r"companysummary_open\(\s*['\"]([^'\"]+)['\"]\s*\).*?>(.*?)</a>",
                heading,
                flags=re.IGNORECASE | re.DOTALL,
            )
            document_match = re.search(
                r"openDisclsViewer\(\s*['\"](\d+)['\"]\s*,\s*['\"](\d+)['\"]\s*\).*?>(.*?)</a>",
                heading,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not document_match:
                continue
            date_match = re.search(
                r"<em\b[^>]*class=[\"'][^\"']*\bdate\b[^\"']*[\"'][^>]*>(.*?)</em>",
                heading,
                flags=re.IGNORECASE | re.DOTALL,
            )
            snippet_match = re.search(r"<a\b[^>]*>(.*?)</a>", detail, re.IGNORECASE | re.DOTALL)
            submitter_match = re.search(
                r"<span\b[^>]*class=[\"'][^\"']*\binText\b[^\"']*[\"'][^>]*>(.*?)</span>",
                detail,
                flags=re.IGNORECASE | re.DOTALL,
            )
            receipt_no, document_no, title_html = document_match.groups()
            filing_id = f"{receipt_no}:{document_no}"
            results.append(
                {
                    "filing_id": filing_id,
                    "receipt_no": receipt_no,
                    "document_no": document_no,
                    "kind_company_code": company_match.group(1) if company_match else None,
                    "filing_company": self._text(company_match.group(2)) if company_match else None,
                    "title": self._text(title_html),
                    "published_at": self._text(date_match.group(1)) if date_match else None,
                    "snippet": self._text(snippet_match.group(1)) if snippet_match else "",
                    "submitter": self._text(submitter_match.group(1)).removeprefix("제출인 : ")
                    if submitter_match
                    else None,
                    "viewer_url": self._viewer_url(receipt_no, document_no),
                }
            )
        return results

    def _is_investment_result(self, filing: dict[str, Any]) -> bool:
        text = f"{filing.get('title') or ''} {filing.get('snippet') or ''}".lower()
        return any(term in text for term in self.INVESTMENT_TERMS)

    def _viewer_url(self, receipt_no: str, document_no: str) -> str:
        return (
            f"{self.base_url}{self.VIEWER_PATH}?method=search"
            f"&acptno={receipt_no}&docno={document_no}&viewerhost=&viewerport="
        )

    def _extract_document_url(self, source: str) -> str | None:
        match = re.search(
            r"parent\.setPath\(\s*['\"][^'\"]*['\"]\s*,\s*['\"]([^'\"]+)['\"]",
            source,
        )
        return urljoin(self.base_url, unescape(match.group(1))) if match else None

    @staticmethod
    def _text(source: str) -> str:
        source = source.replace("&cr;", " ")
        source = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", source, flags=re.I | re.S)
        source = re.sub(r"<br\s*/?>", "\n", source, flags=re.I)
        source = re.sub(r"<[^>]+>", " ", source)
        return " ".join(unescape(source).split())

    @staticmethod
    def _normalize_name(name: str) -> str:
        return re.sub(r"(?:주식회사|㈜|\(주\)|\s+)", "", name).lower()

    @staticmethod
    def _api_error(exc: Exception) -> FinancialApiResponse:
        if isinstance(exc, httpx.HTTPStatusError):
            error = f"KIND HTTP {exc.response.status_code}: {exc.request.method} {exc.request.url.path}"
        elif isinstance(exc, httpx.RequestError):
            error = f"KIND request failed: {exc.__class__.__name__}"
        else:
            error = str(exc)
        return FinancialApiResponse(status=ApiStatus.API_ERROR, error=error)
