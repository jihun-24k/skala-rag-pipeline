# skala-rag-pipeline

SKALA RAG 파이프라인 프로젝트입니다.

Physical AI 스타트업을 대상으로 출처와 불확실성을 추적하면서 기술·시장·재무를 분석하고 투자 의견 보고서를 생성하는 실사형 RAG 프로젝트입니다.

배포용 웹 서비스가 아닌 로컬 Python 프로젝트로 개발합니다. REST API나 FastAPI 서버를 두지 않으며, CLI 또는 Python 함수 호출로 수집·색인·분석·평가를 실행합니다. 데이터와 인덱스는 SQLite, BM25, FAISS 기반 로컬 파일로 관리하는 것을 목표로 합니다.

## 문서

- [전체 구현 설계](docs/implementation-design.md)

## LangGraph 워크플로

현재 구현된 그래프는 다음 순서로 실행됩니다.

```text
START → 시장 분류 ─┬→ 기술 분석 ───┐
                   └→ 시장·경쟁 분석 ─┴→ 재무 분석 → 투자 판단 → 보고서 생성 → END
```

- 기술 분석과 시장·경쟁 분석은 같은 super-step에서 병렬 실행됩니다.
- 재무 분석은 두 분석이 모두 끝날 때까지 기다립니다.
- 각 분석 노드가 추가한 `evidence`는 `evidence_id` 기준으로 병합됩니다.
- 구체적인 LLM, 검색기, 데이터 저장소는 `InvestmentAgents`로 주입합니다.

핵심 파일:

- `src/skala_rag/models/investment.py`: 에이전트별 구조화 결과 모델
- `src/skala_rag/graph/state.py`: 공유 State와 evidence reducer
- `src/skala_rag/agents/interfaces.py`: 6개 에이전트 호출 계약
- `src/skala_rag/graph/workflow.py`: 그래프 노드와 edge 정의

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
