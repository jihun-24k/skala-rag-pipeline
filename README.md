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

## 자료 임베딩과 FAISS 검색

Qwen3-Embedding-0.6B으로 Markdown, JSON, JSONL, PDF 자료를 임베딩하고
FAISS `IndexIDMap2(IndexFlatIP)`와 SQLite 메타데이터를 함께 생성합니다.

```bash
HF_HOME=storage/models uv run skala-rag index build \
  --source storage/raw/자료조사 \
  --output storage/indexes/qwen3-0.6b-v1 \
  --version qwen3-0.6b-v1 \
  --device auto
```

검색 예시:

```bash
HF_HOME=storage/models uv run skala-rag index search \
  --index storage/indexes/qwen3-0.6b-v1 \
  --query "로브로스의 핵심 로봇 기술과 특허" \
  --company-id company-01 \
  --top-k 5
```

색인은 `evidence.faiss`, `metadata.sqlite3`, `manifest.json`으로 구성됩니다.
manifest에는 임베딩 모델·차원·청크 수와 인덱스 파일 체크섬이 기록됩니다.
