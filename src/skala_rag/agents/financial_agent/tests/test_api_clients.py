from __future__ import annotations

import io
import zipfile

import httpx

from skala_rag.agents.financial_agent.api.dart import DartClient
from skala_rag.agents.financial_agent.api.fsc import FscClient
from skala_rag.agents.financial_agent.api.kind import KindClient
from skala_rag.agents.financial_agent.models.schemas import ApiStatus, CompanyRef
from skala_rag.agents.financial_agent.service.normalizer import FinancialNormalizer


def _corp_code_zip() -> bytes:
    xml = b"""<?xml version='1.0' encoding='UTF-8'?>
    <result><list><corp_code>01234567</corp_code><corp_name>Test Robotics</corp_name>
    <stock_code></stock_code><modify_date>20260901</modify_date></list></result>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", xml)
    return buffer.getvalue()


def test_dart_live_flow_selects_latest_report_and_falls_back_to_separate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("corpCode.xml"):
            return httpx.Response(200, content=_corp_code_zip())
        if request.url.path.endswith("company.json"):
            return httpx.Response(
                200,
                json={"status": "000", "jurir_no": "1101111234567", "bizr_no": "1234567890"},
            )
        if request.url.path.endswith("list.json"):
            return httpx.Response(
                200,
                json={
                    "status": "000",
                    "list": [
                        {
                            "report_nm": "분기보고서 (2026.03)",
                            "rcept_no": "20260515000001",
                            "rcept_dt": "20260515",
                        },
                        {
                            "report_nm": "사업보고서 (2025.12)",
                            "rcept_no": "20260330000001",
                            "rcept_dt": "20260330",
                        },
                    ],
                },
            )
        if request.url.path.endswith("fnlttSinglAcntAll.json"):
            if request.url.params["fs_div"] == "CFS":
                return httpx.Response(200, json={"status": "013", "message": "no data"})
            rows = [
                {
                    "sj_div": "IS",
                    "account_id": "ifrs-full_Revenue",
                    "account_nm": "매출액",
                    "thstrm_amount": "300",
                    "thstrm_add_amount": "300",
                    "frmtrm_amount": "250",
                    "frmtrm_add_amount": "250",
                    "currency": "KRW",
                },
                {
                    "sj_div": "BS",
                    "account_id": "ifrs-full_Assets",
                    "account_nm": "자산총계",
                    "thstrm_amount": "1000",
                    "frmtrm_amount": "900",
                    "currency": "KRW",
                },
            ]
            return httpx.Response(200, json={"status": "000", "list": rows})
        raise AssertionError(f"unexpected URL: {request.url}")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = DartClient(api_key="test-key", client=http)
    company = CompanyRef(company_id="test", company_name="Test Robotics")

    response = client.fetch(company, ["revenue", "total_assets"])
    normalized = FinancialNormalizer().normalize(response.data, source="dart")

    assert response.status == ApiStatus.AVAILABLE
    assert response.metadata["report_type"] == "first_quarter"
    assert response.metadata["statement_scope"] == "separate"
    assert company.dart_corp_code == "01234567"
    assert company.corporation_number == "1101111234567"
    assert normalized.revenue.value == 300
    assert normalized.revenue.previous_value == 250
    assert normalized.revenue.previous_as_of == "2025-03-31"
    assert normalized.total_assets.previous_as_of == "2025-12-31"


def test_fsc_summary_response_is_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getIncoStat_V2"):
            return httpx.Response(
                200,
                json={
                    "response": {
                        "header": {"resultCode": "00"},
                        "body": {
                            "items": {
                                "item": [
                                    {
                                        "basDt": "20251231",
                                        "fnclDcdNm": "연결재무제표 [member]",
                                        "acitId": "ifrs-full_Revenue",
                                        "acitNm": "매출액",
                                        "crtmAcitAmt": "1000",
                                        "pvtrAcitAmt": "850",
                                        "curCd": "KRW",
                                    }
                                ]
                            }
                        },
                    }
                },
            )
        if request.url.path.endswith("getBs_V2"):
            return httpx.Response(
                200,
                json={
                    "response": {
                        "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
                        "body": {
                            "items": {
                                "item": [
                                    {
                                        "basDt": "20251231",
                                        "fnclDcdNm": "연결재무제표 [member]",
                                        "acitId": "ifrs-full_CashAndCashEquivalents",
                                        "acitNm": "현금및현금성자산",
                                        "crtmAcitAmt": "300",
                                        "pvtrAcitAmt": "250",
                                        "curCd": "KRW",
                                    }
                                ]
                            }
                        },
                    }
                },
            )
        assert request.url.path.endswith("getSummFinaStat_V2")
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
                    "body": {
                        "items": {
                            "item": [
                                {
                                    "basDt": "20251231",
                                    "fnclDcdNm": "연결재무제표",
                                    "enpSaleAmt": "1000",
                                    "enpBzopPft": "100",
                                    "enpCrtmNpf": "80",
                                    "enpTastAmt": "2000",
                                }
                            ]
                        }
                    },
                }
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = FscClient(api_key="test-key", client=http)
    company = CompanyRef(
        company_id="test",
        company_name="Test Robotics",
        corporation_number="1101111234567",
    )

    response = client.fetch(company, ["revenue", "cash_and_cash_equivalents"])
    normalized = FinancialNormalizer().normalize(response.data, source="fsc")

    assert response.status == ApiStatus.AVAILABLE
    assert set(response.data) == {"revenue", "cash_and_cash_equivalents"}
    assert normalized.revenue.value == 1000
    assert normalized.revenue.previous_value == 850
    assert normalized.revenue.as_of == "2025-12-31"
    assert normalized.cash_and_cash_equivalents.value == 300
    assert normalized.cash_and_cash_equivalents.previous_value == 250
    assert normalized.cash_and_cash_equivalents.statement_scope == "consolidated"


def test_fsc_balance_sheet_absence_preserves_summary_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(("getBs_V2", "getIncoStat_V2")):
            return httpx.Response(
                200,
                json={
                    "response": {
                        "header": {"resultCode": "00"},
                        "body": {"totalCount": 0, "items": {}},
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "00"},
                    "body": {
                        "items": {
                            "item": {"basDt": "20241231", "enpSaleAmt": "182000000"}
                        }
                    },
                }
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = FscClient(api_key="test-key", client=http)
    company = CompanyRef(
        company_id="test",
        company_name="Test Robotics",
        corporation_number="1101111234567",
    )

    response = client.fetch(company, ["revenue", "cash_and_cash_equivalents"])

    assert response.status == ApiStatus.AVAILABLE
    assert set(response.data) == {"revenue"}
    assert response.metadata["balance_sheet_status"] == "company_found_but_financial_not_found"
    assert response.metadata["income_statement_status"] == "company_found_but_financial_not_found"


def test_kind_searches_investment_filings_and_downloads_document() -> None:
    search_html = """
    <section class="total-search bd"><dl>
      <dt class="img">
        <strong class="name"><a onclick="companysummary_open('00680');return false;">미래에셋증권</a></strong>
        <span class="subject"><a onclick="openDisclsViewer('20260814003559', '20260814012534');return false;">반기보고서(2026.06)</a></span>
        <em class="date">2026-08-14 17:31</em>
      </dt>
      <dd><a><b>로브</b><b>로스</b> RCPS 비상장 일반투자</a><span class="inText">제출인 : 미래에셋증권</span></dd>
    </dl></section>
    """
    contents_html = """
    <script>parent.setPath('/external/toc.htm',
    'https://kind.krx.co.kr/external/2026/08/14/report.htm','/external/report','05','20');</script>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("searchtotalinfo.do"):
            return httpx.Response(200, text=search_html)
        if request.url.path.endswith("disclsviewer.do"):
            assert request.url.params["method"] == "searchContents"
            return httpx.Response(200, text=contents_html)
        if request.url.path.endswith("/external/2026/08/14/report.htm"):
            return httpx.Response(200, text="<html><body><h1>타법인 출자</h1><p>로브로스 투자</p></body></html>")
        raise AssertionError(f"unexpected URL: {request.url}")

    http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    client = KindClient(client=http)

    searched = client.search_investment_filings("로브로스")
    assert searched.status == ApiStatus.AVAILABLE
    assert searched.metadata["investment_match_count"] == 1
    filing = searched.data["filings"][0]
    assert filing["filing_company"] == "미래에셋증권"
    assert filing["filing_id"] == "20260814003559:20260814012534"

    document = client.get_document(filing["filing_id"])
    assert document.status == ApiStatus.AVAILABLE
    assert document.data["document_url"].endswith("/external/2026/08/14/report.htm")
    assert "로브로스 투자" in document.data["content_text"]


def test_kind_company_lookup_does_not_mistake_mentioned_company_for_issuer() -> None:
    search_html = """
    <dt class="img"><strong class="name"><a onclick="companysummary_open('00680')">미래에셋증권</a></strong>
    <span class="subject"><a onclick="openDisclsViewer('1', '2')">사업보고서</a></span></dt>
    <dd><a>로브로스 비상장 투자</a></dd>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=search_html)

    client = KindClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    response = client.find_company("로브로스")

    assert response.status == ApiStatus.COMPANY_NOT_FOUND


def test_http_errors_do_not_expose_api_keys() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = FscClient(api_key="secret-api-key", client=http)
    company = CompanyRef(
        company_id="test",
        company_name="Test Robotics",
        corporation_number="1101111234567",
    )

    response = client.get_financial_statements(company)

    assert response.status == ApiStatus.API_ERROR
    assert "secret-api-key" not in (response.error or "")
    assert "serviceKey" not in (response.error or "")
