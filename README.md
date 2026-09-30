# skala-rag-pipeline

SKALA RAG 파이프라인 프로젝트입니다.

Physical AI 스타트업을 대상으로 출처와 불확실성을 추적하면서 기술·시장·재무를 분석하고 투자 의견 보고서를 생성하는 실사형 RAG 프로젝트입니다.

배포용 웹 서비스가 아닌 로컬 Python 프로젝트로 개발합니다. REST API나 FastAPI 서버를 두지 않으며, CLI 또는 Python 함수 호출로 분석·평가를 실행합니다. 기술 분석은 사전에 만든 FAISS 인덱스와 JSONL 메타데이터를 읽을 수 있으며, 그래프 결과는 저장 가능한 JSON 자료로 변환할 수 있습니다.

## 문서

- [전체 구현 설계](docs/implementation-design.md)

## LangGraph 워크플로

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

## 보고서 생성 에이전트

`src/skala_rag/agents/report.py`의 `make_report_writer()`가 `InvestmentAgents.write_report` 계약(`ReportWriter`)을 구현합니다. 분석 결과·투자 판단·evidence만 사용하고 새 자료를 검색하지 않으며, 판단을 바꾸지 않습니다.

```python
from langchain_openai import ChatOpenAI
from skala_rag.agents.report import make_report_writer, render_markdown

write_report = make_report_writer(ChatOpenAI(model="gpt-4o-mini", temperature=0), output_dir="storage/reports")
agents = InvestmentAgents(..., write_report=write_report)
report = build_investment_graph(agents).invoke({...})["report"]
print(render_markdown(report))
```

- 설계서 8장 구조(SUMMARY → … → REFERENCE, 5페이지)를 `InvestmentReport`의 6개 필드에 나눠 담습니다.
- 모든 문장에 evidence ID를 구조화 출력으로 받고, 근거 없는 주장은 1회 재작성 후 제외합니다. 이어서 인용 근거가 문장의 수치·조건을 실제로 뒷받침하는지 한 번 더 검사합니다(Self-RAG식 검증).
- 본문은 `[n]`, `references`는 실제 인용한 자료만 첫 등장 순서로 싣습니다. E 등급은 로드맵으로만 표기하고, `MissingFact`는 "확인 불가 항목" 표로 노출합니다.
- 그래프가 넘겨줄 수 있으면 `scores`, `market_category`를 키워드 인자로 받아 점수표와 스냅샷을 채웁니다.

예시 실행(API 키 불필요, 로브로스 예시 데이터):

```bash
uv run python scripts/example_robros.py --no-pdf        # Markdown만
uv pip install markdown pypdf playwright && uv run playwright install chromium
uv run python scripts/example_robros.py                 # PDF 변환 + 페이지 수 확인
```
# 실제 분석 및 보고서 실행

```bash
uv sync
# 로컬 Qwen 모델과 FAISS로 검색하고 근거·결측값을 보고서로 저장
HF_HOME=storage/models uv run skala-rag analyze \
  --query "로브로스 투자 분석" --as-of-date 2026-09-30

# 모델 다운로드 없이 BM25로 자료·그래프 연결 확인
uv run skala-rag analyze --query "로브로스 분석" --retriever bm25

# 같은 실행을 스크립트로 수행
HF_HOME=storage/models uv run python scripts/generate_report.py \
  --query "로브로스 분석" --as-of-date 2026-09-30

# 저장된 JSON으로 PDF를 다시 생성 (.md도 지원)
uv run skala-rag report --input storage/reports/<run-id>/01_robros.json \
  --output storage/reports/report.pdf
```

출력은 `storage/reports/<run-id>/` 아래의 기업별 PDF, JSON, Markdown, `summary.json`이다.
PDF는 기본 생성되며 브라우저 설치 없이 한글 글꼴을 내장하고 표·참고문헌·페이지 번호를 출력한다.
macOS의 Arial Unicode, Windows의 맑은 고딕, Linux의 NanumGothic을 자동 탐색한다.
다른 환경에서는 `SKALA_PDF_FONT=/path/to/NanumGothic.ttf`를 지정한다.
`--company 로브로스 --company 다른기업`처럼 반복하면 기업마다 독립된 State로 분석한다.
자료 위치는 `--research-root` 또는 `SKALA_RESEARCH_ROOT`로 지정할 수 있다.
FAISS는 기본적으로 `storage/indexes/qwen3-0.6b-v1`을 사용하며 `--index`로 바꾼다.

기본 실행은 LLM과 재무 API를 사용하지 않으며 검색 근거·결측 정보를 출력하고
투자 점수 없이 `추가 실사`로 반환한다. 실제 생성·채점을 사용하려면 `uv sync --extra llm`을
실행하고 `OPENAI_API_KEY`와 `--model <사용할 모델명>`을 설정한다.
재무 수집은 `--financial-api`로 활성화한다. DART/FSC는 해당 키를 환경 또는 `.env`에서
읽으며 KIND는 공개 웹 조회를 사용한다. API/LLM 오류는 성공한 분석으로 감추지 않는다.
재무 어댑터의 기준일 검사는 재무 기간 기준이며 역사적 공시 발표 시점 검증은 별도 과제다.

`runtime.build_runtime_agents()`의 `technology_retriever`, `market_retriever`에 서로 다른
리트리버를 주입할 수 있다. 공통 FAISS 검색 계약은 `EvidenceRetriever.search(RetrievalQuery)`이며,
에이전트 어댑터는 원문 URL·자료 관측일·기업 식별자를 검증한 메타데이터와 조인한다.
기존 인덱스에 없거나 원문 메타데이터와 매칭되지 않는 자료는 제외한다.
FAISS 인덱스에 새 산업 공통 자료를 추가했다면 메타데이터의 `locator`도 해당 파일 경로로 지정한다.

검증: `uv run pytest -q` (재무 에이전트 테스트 포함).
`scripts/run_langgraph.py`는 고정값을 사용하는 그래프 데모이며 실제 실행은 위 명령을 사용한다.
