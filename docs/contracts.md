# 공통 인터페이스 계약

이 문서는 현재 구현의 호출·State·검색 계약과 변경 시 지켜야 할 규칙을 기록한다. 타입의 기준은 `src/skala_rag/agents/interfaces.py`, `src/skala_rag/models/investment.py`, `src/skala_rag/models/orchestration.py`, `src/skala_rag/graph/state.py`, `src/skala_rag/retrieval/models.py` 및 `adapters.py`다. 계약을 바꾸면 코드·이 문서·관련 테스트를 같은 작업에서 갱신한다.

## Supervisor 과제 경로

루트 `app.py`는 기존 CLI에 인자를 전달하는 진입점이다. 인자 없이 실행하면 Supervisor 도움말을 표시하고 `--query` 등 옵션으로 시작하면 `orchestrate`를 기본 명령으로 사용한다. `analyze`/`report`/`index` 명령을 명시하면 해당 CLI 경로를 유지한다. CLI `main(argv=None, prog='skala-rag')`의 선택적 인자는 전달용이며 기존 console entrypoint와 종료 코드는 유지한다.

`app.py`는 저장소 `.venv`가 있으면 그 Python으로 재실행해 프로젝트 의존성을 사용한다. `.venv`가 없으면 호출한 Python을 사용하며 자동 설치하지 않는다. 누락된 의존성 오류에는 `uv sync --extra llm --group dev` 안내를 출력한다.

기존 투자 그래프의 타입·판정·호출 계약은 유지한다. 신규 CLI `orchestrate`와 Python `build_supervisor_graph(OrchestrationAgents, checkpointer=..., recorder=...)`는 `SupervisorState`를 사용한다. `initial_state(query, as_of_date, company=..., run_id=..., limits=...)`가 입력·예산을 검증하고 모든 제어 필드를 초기화한다. run/thread/trace ID는 동일 UUID다. Python 실행은 `invoke_supervisor(graph, state, config=...)`로 자동 prompt/State tracing을 비활성화한다. 재개 입력은 `None`이다. 저수준 `graph.invoke`를 직접 호출할 때는 호출자가 tracing context를 관리한다.

### 요청·결과와 단일 쓰기 원칙

- `OrchestrationAgents.workers`: A~G의 `worker(TaskRequest, State 스냅샷) -> 역할별 payload`. `supervise(State) -> SupervisorDecision`은 선택 주입점이며 미설정이면 결정론적 `SupervisorPolicy`를 사용한다. 작업자와 정책에 원본 State를 전달하지 않고 깊은 복사본을 전달한다.
- A는 `ClassificationPayload`, B/C/D는 `ResearchResult`, E는 `EvaluationSummary`, F는 `EvaluationReport`, G는 `QualityVerdict`를 반환한다. 모든 payload를 역할별 Pydantic 타입으로 검증하고 모르는 필드는 거부한다. E는 과제 경로에서 중립 평가 정리이며 투자 판정 callable을 호출하지 않는다.
- `TaskRequest`는 안정된 `task_id=<run>:<agent>`, `agent`, 1부터 시작하는 `attempt`, 비어 있지 않은 `questions`, `reason`, `based_on_revision`을 포함한다. B/C는 질문을 실제 검색 query에 추가한다. D의 기존 API 수집 계약에는 자유 질의가 없으므로 사업 지속성 자료 수집에 사용하며 임의 질문별 API 검색을 지원한다고 간주하지 않는다.
- 노드 어댑터는 payload 또는 정규화한 오류를 `TaskResult`에 담는다. 결과 상태는 `succeeded`, `insufficient`, `unavailable`, `failed`다. 자료 부족은 실행 오류가 아니다. 오류 메시지 대신 고정된 안전한 요약과 예외 종류를 저장한다.
- 작업자는 `task_results`의 `<task_id>:<attempt>`만 갱신한다. reducer는 같은 결과 재전달을 허용하지만 동일 키의 서로 다른 결과는 거부한다. `collect`가 처리된 키를 기록하고 분석·근거·오류를 한 번 반영한다. Supervisor만 다음 작업·attempt 예약·실행 종료를 결정한다. 에이전트 간 별도 State나 직접 호출은 없다.

### State·버전·오류

| 영역 | 책임과 보존 이유 |
|---|---|
| 식별/입력 | run/thread/trace ID, 스키마·설정·자료 버전, 입력 지문으로 재개 호환성 검사 |
| 현재 산출물 | 기업·분류, `perspectives`, 활성 `evidence`/ID, 평가 정리, 보고서, 품질 verdict |
| 작업 제어 | 요청·결과, 처리된 키, task 상태, `next_action`, agent별 attempts, 무진행 agent |
| 반복 예산 | step/Supervisor 횟수와 검증된 `limits`; 각 연구 최대 3회, F/G 각 최대 3회, Supervisor 20회, 전체 60회, 오류 6회 기본값 |
| Error-aware | 실행 `status`, 누적 `error_count`, `last_error`, 미해결 `task_errors`, task별 `retry_counts` |
| 유효성 | `analysis_revision`, `report_revision`으로 이전 분석의 정리·보고서·평가 사용 방지; `research_sufficient`로 현재 분석의 충분성 판단 보존 |

`ErrorInfo.ts`와 `TaskResult.started_at/completed_at`는 timezone-aware datetime으로 검증한다. 기본 시간은 UTC이며 저장 변환은 ISO 시각 문자열이다. 완료 시각은 시작 시각보다 앞설 수 없다. 외부 문서 발행일·분석 기준일은 기존 `date` 계약을 유지한다.

`error_count`는 최초 수집한 오류에만 증가하고 복구해도 감소하지 않는다. 성공하면 해당 task의 미해결 오류만 제거한다. `last_error`는 마지막 발생 기록이므로 복구 여부는 `task_errors`로 판단한다. `retry_counts`는 오류에 따른 재예약만 세고, 자료 부족 재조사는 `attempts`에 포함한다. 오류 상한은 별도 최상위 키 대신 `limits.max_errors`다.

timeout·연결 실패·429·5xx는 예산 내 재시도한다. 인증·계약·프로그래밍 오류는 반복하지 않는다. B/C/D 실패는 한계와 미해결 오류를 보존한 제한 보고로 이어질 수 있다. 필수 작업·수집 오류는 실패/미완료로 종료한다. 해결되지 않은 오류나 분류 검토가 있으면 Judge가 통과를 제안해도 `passed`가 될 수 없다.

최신 성공 연구 결과만 활성 근거와 관점에 포함한다. 과거 attempt는 호출 상한 내에서 멱등 재개용으로 유지하며 최신 결과로 대체된 근거는 최종 평가에서 제외한다. 같은 evidence ID의 다른 내용은 수집 오류로 처리한다. 연구 주장은 해당 작업이 반환한 근거 ID만 참조하고 다른 기업·기준일 이후 근거는 거부한다. 분석이 변경되면 revision을 증가시키고 E/F/G를 무효화한다. F가 수정되면 report revision을 증가시키며 G의 과거 verdict를 무효화한다.

### 품질·저장·관측성

G는 `groundedness`, `neutrality`, `bias`, `coverage` 각각 하나의 `pass/fail/unknown`을 반환한다. 코드 검사에서 실패한 기준을 의미 Judge가 통과로 바꿀 수 없다. ID·원문 URL·출처 분산·추천 표현·네 관점·선택적 PDF 10쪽 상한을 검사하고, 주장 지지 여부·중립성·독립성은 Judge가 검토한다. 출처 독립성 메타데이터가 없으면 코드 결과는 `unknown`이며 의미 검증이 필요하다. 의미 Judge가 없으면 구조적 통과도 `unknown`으로 남는다. Judge가 오래된 report revision을 평가한 결과는 오류다. 품질 실패의 담당과 질문에 따라 B/C/D 재조사, E 재정리, F 수정 후 G 재평가를 선택한다.

`passed`는 현재 보고서·verdict의 네 기준 통과와 미해결 오류 없음일 때만 허용한다. Supervisor의 충분성 모델이 현재 분석을 불충분하다고 판단하면 `research_sufficient=False`로 보존하고 품질 Judge의 통과로 뒤집지 않는다. 새 연구 결과로 분석 버전이 바뀌면 충분성 판단을 초기화하고 다시 평가한다. 부족한 근거·의미 평가 미확인·재작업 상한은 `incomplete`, 필수 실행 실패는 `failed`다. 동일 연구 결과가 반복되면 무진행으로 표시해 같은 조사 반복을 중지한다. CLI 중단은 가능한 결과 파일에 `interrupted`로 기록하고 마지막 정상 체크포인트를 보존한다.

CLI는 실행 디렉터리에 입력·최종 JSON·Markdown·선택적 PDF, 로컬 이벤트와 SQLite 체크포인트를 저장한다. 재개는 동일 UUID와 입력·설정·자료 SHA-256 지문을 요구한다. FAISS 체크섬 검사와 manifest 내용, 기업 마스터·실제 로드 문서까지 지문에 포함한다. 완료 task를 재사용하지만 중단 당시 완료 여부를 확인하지 못한 외부 호출의 정확히 한 번 실행은 보장하지 않는다. 강제 종료·reducer/DB/저장 오류는 일반 노드 오류처럼 항상 State에 넣을 수 없으므로 실행 경계와 마지막 정상 체크포인트를 확인한다.

LangSmith는 `--langsmith`와 `LANGSMITH_API_KEY`로 명시 활성화한다. 프로젝트는 CLI 옵션 또는 `LANGSMITH_PROJECT`, 기본 `skala-supervisor`다. 루트/하위 노드에 같은 trace ID를 연결하고 재개는 기존 원격 루트의 dotted order를 재사용한다. 허용된 제어 메타데이터와 근거 ID만 전송하며 원문·query·State·모델 prompt는 자동 tracing을 끄고 제외한다. 인증 필드·키 문자열을 가리고 외부 예외 body는 저장하지 않는다. 원격 오류는 로컬 `tracing` 이벤트와 최종 `delivery_status=failed`에 남긴다. `submitted`는 SDK 호출·flush 성공을 의미하며 대시보드 검토·제출 캡처를 대신하지 않는다. 분석 상태와 전송 상태는 분리한다.

## 그래프 입력과 결과

`build_investment_graph(agents, *, checkpointer=None)`에 `InvestmentAgents`를 주입하고 `graph.invoke(...)`로 실행한다.

- `InvestmentInput`: 필수 `as_of_date: str`, 선택 `query: str`, `candidate_companies: list[str | dict[str, object]]`, `current_index: int`.
- 기준일은 ISO 날짜 문자열을 전달한다. 구조화된 `CompanyProfile.as_of_date`는 `datetime.date`다.
- `InvestmentState`: 입력 외에 `current_company`, `company_profile`, `market_category`, `tech_analysis`, `market_analysis`, `competitor_analysis`, `financial_analysis`, `evidence`, `decision`, `scores`, `report`를 가진 부분 상태다. 노드는 선행 노드가 생성한 필드만 사용한다.
- `InvestmentOutput`: 위 결과 필드 중 `current_company`만 선택이고, 나머지 분석·근거·판단·보고서 필드는 필수다. 입력 키 전체가 출력 계약에 포함되는 것은 아니다.
- `to_storage_payload(output)`는 `TypeAdapter(InvestmentOutput)`로 검증한 뒤 JSON 호환 dict로 변환한다. 날짜는 ISO 문자열, 모델은 dict가 되며 DB 저장은 호출자 책임이다.

## 에이전트 호출

아래 인자는 순서대로 전달한다. 각 callable은 입력 객체를 직접 수정하지 않는다.

| 슬롯 | 입력 | 반환 |
|---|---|---|
| `classify_market` | `query: str`, `as_of_date: str` | `ClassificationResult(company_profile, market_category, current_company=None)` |
| `analyze_technology` | `CompanyProfile`, `MarketCategory`, `query: str` | `AnalysisResult[TechAssessment]` |
| `analyze_market` | `CompanyProfile`, `MarketCategory`, `query: str` | `AnalysisResult[MarketAssessment]` 또는 확장 `MarketAnalysisResult` |
| `analyze_financials` | `CompanyProfile`, `TechAssessment`, `MarketAssessment` | `AnalysisResult[FinancialAssessment]` |
| `make_decision` | `TechAssessment`, `MarketAssessment`, `FinancialAssessment`, `list[Evidence]` | `DecisionResult(decision: InvestmentDecision, scores: dict[str, ScoreDetail])` |
| `write_report` | `CompanyProfile`, `TechAssessment`, `MarketAssessment`, `FinancialAssessment`, `InvestmentDecision`, `list[Evidence]` | `InvestmentReport` |

- `AnalysisResult`는 `assessment`와 기본 빈 리스트인 `evidence`를 가진 frozen dataclass다. 내부 모델과 리스트까지 불변인 것은 아니므로 입력 변경 금지는 별도 개발 규칙으로 지킨다.
- 시장 구현의 `MarketAnalysisResult`는 `competitor_analysis: CompetitorAnalysis`를 추가한다. 기본 결과만 반환하면 그래프는 빈 `CompetitorAnalysis()`를 사용한다.
- 분류 callable에 `classify_state`가 있으면 그래프가 `classify_state(state)`를 호출한다. 이 확장은 일반 `MarketClassifier` callable 타입과 별도이며 반환은 동일한 `ClassificationResult`다.
- `ReportWriter` Protocol의 추가 인자는 키워드 전용 `scores: dict[str, ScoreDetail] | None = None`, `market_category: MarketCategory | None = None`이다. 그래프는 해당 이름 또는 `**kwargs`를 받는 작성기에만 전달해 기존 6개 위치 인자 작성기와 호환된다.
- 기술·시장 호출에는 기준일 인자가 따로 없다. `CompanyProfile.as_of_date`를 사용한다. 재무 callable에도 원래 query나 State 전체가 전달되지 않는다.

## 노드 업데이트와 라우팅

정상 경로는 분류 → 기술·시장 병렬 분석 → 두 결과 합류 → 재무 → 투자 판단 → 보고서다.

| 노드 | 반환하는 State 키 |
|---|---|
| 분류 | `company_profile`, `market_category`, 선택 `current_company` |
| 기술 | `tech_analysis`, `evidence` |
| 시장 | `market_analysis`, `competitor_analysis`, `evidence` |
| 재무 | `financial_analysis`, `evidence` |
| 투자 판단 | `decision`, `scores` |
| 보고서 | `report` |

`market_category.review_required`가 참이거나 기업 형태/하위 산업이 빈 문자열, `분류 검토 필요`, `미확정`, `미확인`, `unknown`, `unclassified` 중 하나면 `classification_review` → END로 끝난다(공백 제거·casefold 후 비교). 이 노드는 빈 분석과 결측 사유, 빈 점수, `추가 실사` 판단·보고서를 만들며 기술·시장·재무·판단·보고서 callable을 실행하지 않는다.

`evidence`만 `merge_evidence` reducer로 병렬 갱신한다. `evidence_id`로 중복을 제거하고 최초 등장 순서를 유지한다. 기존 State의 ID와 중복되는 업데이트는 기존 근거를 보존하며, 새 ID가 업데이트에 반복되면 그 업데이트의 첫 값을 사용한다. 같은 ID에 다른 내용을 넣어 덮어쓰는 용도로 사용하지 않는다. 근거가 다르면 다른 안정적인 ID를 생성한다.

## 모델·근거·결측값

- 도메인 모델은 Pydantic `extra="forbid"`로 정의되어 추가 필드를 허용하지 않는다. 타입 정의만으로 모든 에이전트 출력·의미가 런타임에 자동 검증되지는 않으므로 어댑터와 테스트에서도 확인한다.
- `Evidence` 필수 필드: `evidence_id`, `claim_text`, `stance`, `source_type`, `source_grade`, `source_uri`. `stance`는 `support`/`contradict`/`unknown`, 등급은 `A`~`E`다. 선택 출처·시점·기업·지표 메타데이터를 보존한다.
- 분석·판단·점수의 `evidence_ids`는 최종 근거 목록에 존재하는 ID를 가리켜야 한다. 이 참조 무결성은 문자열 리스트 타입만으로 검사되지 않는다.
- `MissingFact(field, reason, attempted_queries=[], sources_checked=[])`로 결측 사유와 확인 경로를 기록한다. 값이 없다고 0 또는 검증된 사실로 바꾸지 않는다.
- `FinancialAssessment.status`는 `available`/`unavailable`이며 기본값은 `unavailable`이다. 현재 재무 어댑터는 동일 기준일·연결범위·단위의 매출과 총자산을 확인해야 `available`로 반환한다. 기간이 분석 기준일보다 미래인 값은 제외하지만 역사적 공시 발표 시점까지 검증하는 계약은 아직 아니다.
- `InvestmentDecision.decision`은 `투자`, `조건부 투자`, `추가 실사`, `투자 제외` 중 하나다. `total_score`는 선택이며 0~100, `confidence`는 0~1이다. `ScoreDetail.score`는 0~100, `weight`는 0~1이다.
- 보고서 필수 문자열은 `summary`, `technology`, `market_competition`, `financials`, `risks`, `decision`이고 `references`는 기본 빈 리스트다. 보고서 작성기는 전달받은 근거와 판단을 사용하며 새 사실을 검색·생성하거나 투자 판단을 바꾸지 않는다.

## 공통 검색 계약

`EvidenceRetriever.search(request: RetrievalQuery) -> list[RetrievalHit]`를 사용한다.

- `RetrievalQuery` 필수 필드는 `query: str`다. 선택 필터는 `company_id`, `source_grades`, `dimensions`, `source_paths`, 선택 `instruction`이다. `top_k`는 기본 10, 범위 1~100이고 `fetch_k`는 지정하면 1 이상이다.
- `RetrievalHit`는 `vector_id`, `score`, `chunk_id`, `document_id`, `title`, `text`, `source_path`, `source_type`, `source_grade`, `dimension` 및 선택 `locator`, `company_id`, `company_name`을 반환한다.
- 검색 모델도 `extra="forbid"`다. 빈 검색은 빈 리스트로 반환하고 없는 결과를 근거로 만들지 않는다.
- 벡터 결과의 `source_path`는 원문 URL과 동일하지 않다. 에이전트 어댑터가 검증된 원문 메타데이터와 조인해야 하며 매칭되지 않는 청크는 제외한다. 검색 점수를 사실 신뢰도와 동일하게 간주하지 않는다.

시장/런타임 검색 어댑터 계약은 다음과 같다.

```python
search(query: str, *, scope: str, company_ids: set[str],
       forms: set[str], as_of_date: date,
       limit: int = 5) -> list[RetrievedChunk]
```

`FaissMarketRetriever`는 기업/산업 scope, 기업 ID/형태, 관측일과 발표일을 검증하고 E 등급·미래 계획 자료를 제외한다. `RetrievedChunk`의 원문 자료, 청크 ID, 위치와 검색 점수를 보존한다. 공통 `RetrievalQuery`에 기준일 필드는 없으므로 시점 검증을 이 어댑터 계층에서 유지한다.

## B·E 구현 연결

현재 런타임 연결은 `src/skala_rag/runtime.py`가 관리한다. 아래 예시는 `tech_agents/tech.py`와 `decision_agents/decision.py` 구현을 직접 주입하는 별도 연결 방식이다. 필요한 콜백은 호출자가 제공한다.

```python
from functools import partial
from skala_rag.agents.tech_agents.tech import load_faiss_search, technology_node
from skala_rag.agents.decision_agents.decision import decision_node

search = load_faiss_search(index_path, metadata_path, embed_query)
analyze_technology = partial(
    technology_node, search=search,
    judge_context=judge_context, judge_claims=judge_claims,
)
make_decision = partial(decision_node, score=propose_scores)
# 나머지 슬롯과 함께 InvestmentAgents에 주입한다.
```

- B의 `load_faiss_search`는 FAISS와 JSONL을 읽는 방식이며 공통 검색 서비스의 SQLite 메타데이터와 혼용하지 않는다. JSONL은 인덱스와 일치하는 고유 정수 `faiss_id`, `company_id` 및 Evidence 필수 필드를 가진다. `embed_query`는 색인과 동일한 모델·전처리를 사용한다. 기업·입장·명시된 발표일을 필터링하고, 팀 근거는 `topic="team"`으로 표시한다. 색인 생성·크롤링은 이 함수의 역할이 아니다.
- `judge_context(question, response, context)`는 청크별 `bool`, `judge_claims(question, contexts, response)`는 원자적 주장별 `claim_text`·`supported` 목록을 반환한다. 둘을 함께 주입하면 `rag_evaluation`에 입장별 순위 정밀도의 평균과 근거 있는 주장 비율을 기록한다. 평가기를 둘 다 생략하면 `None`이며 하나만 주입하면 오류다. 정답 문서 레이블이나 Ragas 패키지를 직접 사용하는 경로는 아니다.
- E의 `propose_scores(view, evidence)`는 `team`, `market`, `technology`, `traction`, `moat`, `scalability`에 1~5점, `evidence_ids`, `rationale`, 선택 `confidence`를 제안한다. E는 A~D등급 인용 근거를 확인하고 그래프의 0~100점·0~1 가중치로 변환한다. 재무자료가 `unavailable`이면 채점 콜백을 호출하지 않고 `추가 실사`를 반환한다.

## 계약 검증

| 변경 대상 | 기존 검사 |
|---|---|
| State·reducer·출력 변환·병렬 합류 | `tests/graph/test_workflow.py` |
| 분류 검토 조기 종료 | `tests/graph/test_classification_review.py`, `tests/agents/test_classification_edges.py` |
| 시장 결과 확장·그래프 연결 | `tests/graph/test_market_competition_integration.py` |
| 검색·인덱스·메타데이터 | `tests/retrieval/test_faiss_pipeline.py` |
| 기술·판단 | `tests/agents/test_b_e.py` |
| 보고서 | `tests/agents/test_report_writer.py` |
| 재무 | `src/skala_rag/agents/financial_agent/tests/`, `tests/test_runtime.py` |
| 런타임 주입·실행 | `tests/test_runtime.py` |

공통 계약 변경 후 `uv run pytest -q`로 전체 회귀를 확인한다. 필드 추가·삭제·기본값 변경 시 위 기존 검사를 먼저 확인하고, 영향을 받는 호출자·저장 변환·실패 경로의 검사 부족분을 보완한다. 현재 별도 정적 타입 검사 명령은 프로젝트에 설정되어 있지 않다.
