# 투자평가 B·E 에이전트

B·E는 기존 LangGraph의 `InvestmentAgents` 계약을 그대로 사용합니다. 별도 State 모델을 만들지 않으며, 결과는 `src/skala_rag/models/investment.py`의 Pydantic 모델입니다.

| 에이전트 | 그래프 입력 | 반환 |
| --- | --- | --- |
| 기술 분석 B | `CompanyProfile`, `MarketCategory`, `query` | `AnalysisResult[TechAssessment]` (`assessment`, `evidence`) |
| 투자 판단 E | `TechAssessment`, `MarketAssessment`, `FinancialAssessment`, `list[Evidence]` | `DecisionResult` (`decision`, `scores`) |

```python
from functools import partial

from skala_rag.agents.decision import decision_node
from skala_rag.agents.tech import load_faiss_search, technology_node

# 나머지 네 에이전트 구현과 함께 InvestmentAgents에 전달합니다.
search_evidence = load_faiss_search(
    "storage/evidence.faiss", "storage/evidence.jsonl", embed_query
)
analyze_technology = partial(
    technology_node,
    search=search_evidence,
    judge_context=judge_context,
    judge_claims=judge_claims,
)
make_decision = partial(decision_node, score=propose_scores)
```

`load_faiss_search`는 사전에 만든 FAISS 인덱스와 같은 순서의 JSONL 메타데이터를 한 번 읽습니다. JSONL 각 줄에는 고유 정수 `faiss_id`, `company_id`, `evidence_id`, `claim_text`, `stance`, `source_type`, `source_grade`, `source_uri`가 필요합니다. `embed_query`는 인덱스 생성 때와 같은 모델·전처리로 질의를 벡터화해야 합니다. 검색 결과는 기업·기준일·`support`/`contradict`/`unknown`별로 필터링합니다. 인덱스 생성과 크롤링은 이 모듈에 포함되지 않습니다. 팀 관련 근거는 `topic="team"`을 사용합니다.

`judge_context(question, response, context)`는 검색된 각 청크의 유용성을 `bool`로 반환합니다. `judge_claims(question, contexts, response)`는 생성 문장을 원자적 주장으로 나눠 `[{"claim_text": "...", "supported": True/False}]`를 반환합니다. 두 함수를 함께 주입해야 RAG 평가를 실행합니다. `TechAssessment.rag_evaluation`에는 순위 기반 Context Precision(세 입장별 점수의 평균)과 근거가 있는 주장 비율인 Faithfulness가 0~1로 기록됩니다. 정답 문서 레이블은 필요하지 않습니다. LLM 평가기를 아직 연결하지 않으면 점수를 만들어 넣지 않고 `None`으로 둡니다. 이는 [Ragas의 Context Precision](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/)·[Faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/) 공식을 참고한 구현이며, Ragas 패키지를 직접 실행하는 것은 아닙니다.

`propose_scores`는 분석 결과와 A~D등급 근거를 받아 여섯 항목 `team`, `market`, `technology`, `traction`, `moat`, `scalability`에 각각 1~5점, `evidence_ids`, `rationale`, 선택적 `confidence`를 제안합니다. E는 인용 ID와 근거 수준을 검사한 후 그래프 모델의 `ScoreDetail.score`를 0~100점, `weight`를 0~1 비율로 변환합니다. 재무자료가 `unavailable`이면 채점 함수를 호출하지 않고 `추가 실사`를 반환합니다.

## 저장 계층에 넘길 결과

```python
from skala_rag.graph import to_storage_payload

result = graph.invoke({"query": "기업 분석 요청", "as_of_date": "2026-09-30"})
payload = to_storage_payload(result)
# payload는 날짜가 ISO 문자열인 JSON 호환 dict입니다.
# PostgreSQL JSONB 등 저장 계층이 준비되면 payload를 전달하면 됩니다.
```

이 함수는 그래프 출력의 필수 필드를 검증하고 `company_profile`, 세 분석, `evidence`, `scores`, `decision`, `report`를 직렬화합니다. DB 연결이나 쓰기는 하지 않습니다. 검색기·LLM도 호출자가 주입하며, 서버 주소와 인증값은 코드에 넣지 않았습니다.

## 실행 확인

```bash
.venv/bin/python -m pytest -q
```

테스트는 실제 LangGraph 안에서 B·E를 호출하고, 작은 FAISS 인덱스를 읽어 필터링하며, 고정 판정으로 두 RAG 점수와 JSON 변환을 확인합니다.
