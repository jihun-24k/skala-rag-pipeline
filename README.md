# skala-rag-pipeline

SKALA RAG 파이프라인 프로젝트입니다.

Physical AI 스타트업을 대상으로 출처와 불확실성을 추적하면서 기술·시장·재무를 분석하고 투자 의견 보고서를 생성하는 실사형 RAG 프로젝트입니다.

배포용 웹 서비스가 아닌 로컬 Python 프로젝트로 개발합니다. REST API나 FastAPI 서버를 두지 않으며, CLI 또는 Python 함수 호출로 분석·평가를 실행합니다. 기술 분석은 사전에 만든 FAISS 인덱스와 JSONL 메타데이터를 읽을 수 있으며, 그래프 결과는 저장 가능한 JSON 자료로 변환할 수 있습니다.

## 문서

- [전체 구현 설계](docs/implementation-design.md)

## LangGraph 워크플로

<<<<<<< HEAD
현재 구현된 그래프는 다음 순서로 실행됩니다.

```text
START → 시장 분류 ─┬→ 기술 분석 ───┐
                   └→ 시장·경쟁 분석 ─┴→ 재무 분석 → 투자 판단 → 보고서 생성 → END
```

- 기술 분석과 시장·경쟁 분석은 같은 super-step에서 병렬 실행됩니다.
- 분류 결과가 `review_required`이거나 형태 미확정이면 평가 에이전트를 건너뛰고 `추가 실사` 보고서를 반환합니다.
- 재무 분석은 두 분석이 모두 끝날 때까지 기다립니다.
- 각 분석 노드가 추가한 `evidence`는 `evidence_id` 기준으로 병합됩니다.
- 구체적인 LLM, 검색기, 데이터 저장소는 `InvestmentAgents`로 주입합니다.

핵심 파일:

- `src/skala_rag/models/investment.py`: 에이전트별 구조화 결과 모델
- `src/skala_rag/graph/state.py`: 공유 State와 evidence reducer
- `src/skala_rag/agents/interfaces.py`: 6개 에이전트 호출 계약
- `src/skala_rag/agents/market_classification/`: A 접수·시장분류 구현과 기업 마스터 어댑터
- `src/skala_rag/agents/market_competition/`: C 시장·경쟁 RAG, 출처 검증과 산업 공통 자료 검색
- `src/skala_rag/graph/workflow.py`: 그래프 노드와 edge 정의

B·E 구현은 기존 `InvestmentAgents`에 주입할 수 있습니다. `to_storage_payload(result)`는 그래프 결과를 JSON 호환 자료로 변환하며 DB에 직접 저장하지 않습니다. 그래프 연결과 변환 검사는 `uv run pytest -q`로 확인합니다.

```python
from skala_rag.agents import InvestmentAgents
from skala_rag.graph import build_investment_graph

agents = InvestmentAgents(
    classify_market=classify_market,
    analyze_technology=analyze_technology,
    analyze_market=analyze_market,
    analyze_financials=analyze_financials,
    make_decision=make_decision,
    write_report=write_report,
)
graph = build_investment_graph(agents)

result = graph.invoke(
    {"query": "분석할 기업과 요청", "as_of_date": "2026-09-30"}
)
```

## 개발 환경

```bash
uv sync --group dev
uv run pytest -q
```

A 에이전트의 입력·출력, 신규 기업 조사 경로와 실제 10개사 자료 연결 방법은 [시장분류 에이전트 안내](src/skala_rag/agents/market_classification/README.md)에 정리했습니다. 현재 기업 마스터는 `../자료조사/data/company_master.json`에 있으며, 다른 위치에서 실행할 때는 `SKALA_RESEARCH_ROOT`를 설정합니다.

C의 실행 방법, 모델 연결, 산업 공통 자료 입력 양식은 [시장·경쟁 에이전트 안내](src/skala_rag/agents/market_competition/README.md)에 정리했습니다. 기본 실행은 로컬 자료 검색이며, 구조화 생성 모델을 주입하면 인용을 포함한 분석 초안을 반환합니다.
=======
Python 3.11 이상과 `uv`를 기준으로 한다.

```bash
uv sync --extra dev
cp .env.example .env
uv run python -m financial_agent.main
uv run pytest
```

`financial_agent.main`은 외부 API 없이 DART → FSC → KIND 보완 흐름을 확인하는
mock 실행 경로다. 실제 키는 `.env`에서 읽으며 secret은 소스에 저장하지 않는다.

## Financial Agent 실행

외부 API를 호출하지 않는 구조 검증용 mock 실행:

```bash
uv run python -m financial_agent.main --mode mock --company-name 로브로스
```

`.env`의 DART/FSC 키와 KIND 공개 검색을 사용하는 실제 공개자료 조회:

```bash
uv run python -m financial_agent.main --mode live --company-name 로브로스
```

최종 출력은 `financial_data` 한 개의 객체이며 재무값, `evidence_ids`,
`missing_facts`, `as_of`, `status`를 포함한다. `live` 모드여도 비상장 기업에
공개 재무제표가 없으면 값을 추정하지 않고 결측값으로 반환한다.

- FSC는 기업 재무 요약, 상세 손익계산서(`getIncoStat_V2`), 상세 재무상태표를 조회한다.
- KIND는 별도 키 없이 공개 통합검색 HTML과 공시 뷰어를 조회한다. 검색 결과는
  `KindClient.search_investment_filings()`, 원문은 `KindClient.get_document()`로 가져온다.

## Python 코드에서 사용

단일 기업은 기업명만 전달할 수 있다.

```python
from financial_agent import get_financial_data

financial_data = get_financial_data("로브로스")
```

여러 기업은 하나의 Agent와 API 클라이언트를 재사용하는 배치 함수를 사용한다.

```python
from financial_agent import get_financial_data_batch

results = get_financial_data_batch(["로브로스", "삼성전자", "현대자동차"])
loboros = results["로브로스"]
```

동명이거나 이미 식별번호를 알고 있으면 `CompanyRef`를 전달한다.

```python
from financial_agent import CompanyRef, get_financial_data_batch

results = get_financial_data_batch([
    CompanyRef(
        company_id="loboros",
        company_name="로브로스",
        corporation_number="1341110561072",
        dart_corp_code="02052432",
    )
])
```
>>>>>>> 0df6358 (feat: DART·FSC·KIND 연동 재무 분석 에이전트 구현)
