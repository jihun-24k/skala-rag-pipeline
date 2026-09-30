# 투자평가 B·E 에이전트

B·E는 기존 LangGraph의 `InvestmentAgents` 계약을 그대로 사용합니다. 별도 State 모델을 만들지 않으며, 결과는 `src/skala_rag/models/investment.py`의 Pydantic 모델입니다.

| 에이전트 | 그래프 입력 | 반환 |
| --- | --- | --- |
| 기술 분석 B | `CompanyProfile`, `MarketCategory`, `query` | `AnalysisResult[TechAssessment]` (`assessment`, `evidence`) |
| 투자 판단 E | `TechAssessment`, `MarketAssessment`, `FinancialAssessment`, `list[Evidence]` | `DecisionResult` (`decision`, `scores`) |

```python
from functools import partial

from skala_rag.agents.decision import decision_node
from skala_rag.agents.tech import technology_node

# 나머지 네 에이전트 구현과 함께 InvestmentAgents에 전달합니다.
analyze_technology = partial(technology_node, search=search_evidence)
make_decision = partial(decision_node, score=propose_scores)
```

`search_evidence`는 `company_id`, `as_of_date`, `query`, `stance`, `limit` 키워드 인자를 받습니다. `stance`는 그래프 모델과 같은 `support`/`contradict`/`unknown`입니다. 검색 결과에는 `evidence_id`, `claim_text`, `source_type`, `source_grade`, `source_uri`, `stance`가 필요합니다. 기술 노드는 기준일 이후 자료를 제외하고, 채택한 결과를 `Evidence`로 검증합니다. 팀 관련 근거는 `topic="team"`을 사용합니다.

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

테스트는 실제 LangGraph 안에서 B·E를 호출하고, 외부 검색·LLM·DB 대신 고정 입력으로 판정과 JSON 변환을 확인합니다.
