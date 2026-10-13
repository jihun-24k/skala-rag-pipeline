# Subject

본 프로젝트는 Physical AI 기업의 로봇 기술을 선정하여 **기술 성숙도·시장·이해관계자·도메인 적용** 관점에서 근거 기반으로 평가하는 **Supervisor 패턴**의 Multi-Agent Orchestration 프로젝트입니다. 기업별 공개 자료를 조사하고, 부족한 근거를 재조사하며, 별도 품질 평가를 거쳐 중립적인 보고서를 생성합니다.

현재 기준은 [Multi-Agent Orchestration 과제](https://app.notion.com/p/3f8b7788ac2a80f48845e9e9fc755e89)입니다. 하위 [AI 스타트업 투자 평가](https://app.notion.com/p/48db7788ac2a835b84cf810d2c6b6d72)는 이전 과제로, 기업 평가 주제와 기존 보고서 구성을 계승합니다. 이전의 순차·병렬 실행과 5쪽 제한을 이번 기준으로 적용하지 않습니다.

- 기존 14개 목차(SUMMARY, INVESTMENT SNAPSHOT, BUSINESS IDEA, PRODUCT & TECHNOLOGY, MARKET, COMPETITION & MOAT, TRACTION, TEAM, FINANCIALS, VALUATION, KEY RISKS, INVESTMENT DECISION, LIMITATIONS, REFERENCE)를 유지합니다. 판단 장은 근거·반대 논거·추가 실사 조건을 서술하며 근거 없는 점수·추천을 생성하지 않습니다.
- SUMMARY는 전체 핵심 요약으로 반 페이지 이내, PDF 전체는 REFERENCE 포함 최대 10쪽입니다. 정확히 10쪽을 채우는 목표는 아닙니다.
- REFERENCE는 실제 본문/SUMMARY에 사용된 자료만 담습니다. 서지 정보가 없는 경우 미확인으로 표시하며 저자·자료 제목을 만들어 넣지 않습니다.
- 노션 표에 남은 관점 커버리지는 강의 중 제외한다는 구두 정정을 따릅니다. 필수 품질 항목은 근거성·중립성·편향 통제이며, 목차와 분량은 별도 형식 검사입니다. 내부 네 관점은 팀의 조사 구조입니다.

작업 브랜치는 `Multi-Agent-Orchestration`입니다. 실행 진입점은 루트 `app.py`, 로컬 CLI와 Python 함수입니다.

## Overview

- **Objective:** 하나의 기업·기술을 복수 관점에서 평가하고, 출처·조건·한계를 확인할 수 있는 보고서를 작성합니다.
- **Pattern:** Supervisor — 조사 역할이 정해진 기존 에이전트 중에서 현재 부족한 관점을 담당하는 에이전트를 선택하고 재호출하기에 적합합니다.
- **동적 처리:** 고정된 순서로 모든 단계를 반복하지 않습니다. 시장 근거가 부족하면 C만 재조사하고, 인용·표현 문제는 F만 수정한 뒤 G가 다시 평가합니다. 기업 분류가 미확정이면 B/C/D 조사를 생략하고 제한 보고를 작성합니다.
- **평가 원칙:** 과제 경로에서는 기술 우열·투자·구매를 추천하지 않습니다. 확인되지 않은 사실은 `MissingFact`, 검증하지 못한 품질 기준은 `unknown`으로 남깁니다.

## Selected Technologies

- **평가 대상:** 사용자가 지정한 Physical AI 기업의 로봇 제품·기술. 현재 실행 예시는 로브로스이며, 기업 마스터와 공개 근거로 기업·제품 형태를 먼저 확인합니다.
- **선정 이유:** 제품 사양·시험 조건·현장 적용·고객 요구·사업 지속성을 서로 다른 근거로 검토할 수 있는 분야이기 때문입니다.
- **평가 범위:** 기술 성숙도, 시장 수요·경쟁, 고객·운영자·규제기관 등 이해관계자, 실제 도메인의 적용 조건과 제약입니다. 재무자료는 사업 지속성을 보완합니다.

## Features

- **자료 적재:** PDF·Markdown·JSON·JSONL 로컬 자료의 텍스트 추출, 청킹, FAISS 색인과 SQLite 메타데이터 저장. PDF는 텍스트 추출 방식이며 OCR은 포함하지 않습니다.
- **근거 검색:** 기존 FAISS 색인이 있으면 우선 사용하고 없으면 BM25 검색을 연결하고 기업·기준일·출처 등급을 확인합니다. 실행 시 기업 마스터와 출처 manifest가 필요합니다.
- **관점별 평가:** B/C/D의 조사 결과를 E가 네 관점으로 정리하고 F가 인용된 보고서로 작성합니다.
- **동적 재작업:** 근거 부족, 평가 실패, 일시적 호출 오류를 구분하고 담당 조사·보고서 수정·오류 재시도로 분기합니다.
- **확증 편향 방지 전략:** 독립 출처와 반대·불확실 근거를 확인하며 출처 분산을 검사합니다. 서로 다른 도메인이라는 이유만으로 독립성을 확정하지 않습니다.
- **보고서 품질 평가:** 별도 G가 근거 연결성·중립성·편향을 코드 검사와 의미 Judge로 평가하고 기존 목차·SUMMARY 분량을 별도 검사합니다. PDF 생성 시 최대 10쪽도 검사합니다.
- **재개·관측성:** SQLite 체크포인트로 실행을 재개하고 로컬 이벤트와 선택적 LangSmith trace에 노드 선택·사유·시도·시간을 기록합니다.
- **산출물:** Markdown·PDF·구조화 JSON과 실행 상태 `passed`/`incomplete`/`failed`를 저장합니다.

## Tech Stack

- **Framework:** Python 3.11+, LangGraph, Pydantic v2.
- **LLM/Generator:** LangChain OpenAI 구조화 출력. GPT 모델명은 `--model`로 지정하며 현재 고정된 모델 버전은 없습니다.
- **LLM/Judge:** `--judge-model`로 별도 GPT 모델을 지정합니다. 생략하면 Generator 모델을 사용하며, 모두 미설정이면 의미 평가는 `unknown`입니다.
- **Retrieval:** BM25 기본, FAISS + SQLite 메타데이터 선택. **Hit Rate@K·MRR은 미측정**이며 검증용 정답 문서 집합이 필요합니다.
- **Embedding:** 오픈소스 `Qwen/Qwen3-Embedding-0.6B`, 1024차원. FAISS 경로에서 로컬 실행합니다.
- **Persistence / Tracing:** SQLite 체크포인터, 로컬 JSONL 이벤트, 선택적 LangSmith 전송.
- **Report:** ReportLab PDF, Markdown, JSON.

## Agents

- **Supervisor:** State·오류·근거 충분성·품질 결과를 확인하고 다음 작업과 종료를 결정합니다. 모델의 제안도 코드가 선행 조건과 예산으로 검증합니다.
- **Agent A — 기업·시장 분류:** 기업 동일성, Physical AI 형태와 분석 범위를 확인하고 분류 검토 여부를 반환합니다.
- **Agent B — 기술 분석:** 제품·논문·특허·시험 근거로 기술 성숙도와 도메인 적용 조건을 조사합니다.
- **Agent C — 시장·이해관계자 분석:** 시장 수요·경쟁, 고객·운영자 요구, 독립 출처와 반대 근거를 조사합니다.
- **Agent D — 재무 분석:** DART·FSC·KIND 자료의 출처와 기준일을 확인해 사업 지속성을 보완합니다. API 미사용·자료 미확보는 한계로 남깁니다.
- **Agent E — 평가 정리:** 조사 근거와 결측·오류를 네 관점의 중립 평가로 정리합니다.
- **Agent F — 보고서 생성:** `SUMMARY`부터 `REFERENCE`까지 근거 ID와 원문 URL이 연결된 보고서를 작성·수정합니다.
- **Agent G — 보고서 품질 평가:** 완성된 보고서를 별도로 평가하고 실패 기준의 담당과 재작업 질문을 반환합니다.

작업자는 `TaskRequest`와 State 스냅샷을 받고 결과를 반환합니다. 서로 직접 호출하지 않으며, 모든 작업 선택은 Supervisor를 거칩니다. 기존 `analyze` 경로의 E 투자 판단과 과제 경로의 E 평가 정리는 별도 계약입니다.

기존 모듈 기여자는 다음과 같습니다. 실제 협업 작업 범위는 [AGENTS.md](AGENTS.md)에 따라 개별 작업에서 할당합니다.

| 이름 | 기존 담당 영역 |
|---|---|
| 김지훈 | LangGraph, VectorDB |
| 박시현 | 투자보고서 생성 Agent |
| 이병길 | 재무 정보 수집 Agent |
| 이수빈 | 설계 |
| 최병준 | Tech Agent, Decision Agent |
| 최유정 | 접수/분류 Agent, 시장/경쟁 Agent |

## State Schema

- **제어 vs 페이로드 분리:** 작업 선택·요청·상태·예산은 제어 필드, 기업·관점별 분석·근거·보고서·품질 결과는 페이로드입니다. 오류는 `error_count`, `last_error`, `task_errors`, `retry_counts`로 관리합니다.
- **관측성 위치:** 결정 이력은 로컬 `events.jsonl`과 LangSmith에 기록합니다. State에는 현재 결정·작업 결과·복구 정보만 보존합니다. 원문·질문·전체 State·모델 prompt는 LangSmith 전송에서 제외합니다.
- **지속성 비용:** 원문 문서는 외부 자료 디렉터리에 두고 State에는 근거 인용·요약·참조를 저장합니다. 과거 작업 결과는 호출 상한 내에서 멱등 재개를 위해 보존합니다.
- **상관:** `run_id`/`thread_id`/`trace_id`를 같은 UUID로 연결합니다. 안정된 task ID와 attempt로 결과·오류·trace를 연결하고, 분석·보고서 revision으로 오래된 결과를 구분합니다. 오류·작업 시작·완료 시각은 timezone-aware UTC입니다.
- **재개/복구:** SQLite에 체크포인트를 저장하고 동일 UUID·입력·자료·설정 지문으로 재개합니다. 완료 결과를 재사용하지만 중단 당시 완료 여부를 알 수 없는 외부 호출은 다시 실행될 수 있습니다.
- **동시 처리:** 선택된 독립 조사 작업을 병렬 실행합니다. 작업자는 `task_results`만 쓰고 reducer가 task/attempt 키로 병합하며 동일 키의 다른 결과는 거부합니다. 수집 노드가 활성 근거·분석·오류를 합친 뒤 Supervisor로 돌아갑니다.
- **종료 보장:** 연구별 최대 3회, F/G 각각 최대 3회, Supervisor 최대 20회, 전체 최대 60회, 오류 최대 6회가 기본 상한입니다. 무진행 감지와 graph recursion limit도 적용합니다. 충분성 미충족·미해결 오류·품질 `unknown`은 `passed`로 처리하지 않습니다.

### 강의 State 예시의 적용 근거

이 과제는 **Supervisor**를 선택했습니다. State는 평가 실행별 공유 작업 상태이며, 에이전트마다 독립 State를 추가하지 않습니다. 아래 각주는 설계 이유와 제출 시 확인할 증거를 연결합니다. 예시의 필드명은 그대로 복사하지 않고 기업 평가 목적에 맞춰 대응했습니다.

| 강의 예시 / 항목 | 실제 필드 | 설계 이유 |
|---|---|---|
| `selected_tech`, `target_domain` | `company_profile`, `market_category`, `as_of_date` | 기술 목록보다 평가 기업·유형·시장·기준일이 조사 범위를 결정함[^state-input] |
| `perspectives`, `sources` | `perspectives`, `evidence`, `active_evidence_ids` | 주장과 근거 ID를 연결하고 최신 연구 결과만 활성화함[^state-payload] |
| `synthesis`, `report`, `eval_result` | `evaluation_summary`, `report`, `quality_result` | 종합·초안·품질판정을 분리하고 이전 버전의 통과 결과 재사용을 막음[^state-version] |
| 제어 / 작업 결과 분리 | `next_action`, `pending_tasks`, `task_results`, `task_status` | 다음 대상·질문을 결정하는 제어 정보와 작업 산출물을 구분함[^state-route] |
| 관측성 / 상관 | `trace_id`, `run_id`, `thread_id` | 전체 결정 이력은 외부 로그에 두고 같은 실행을 연결함[^state-trace] |
| 지속성 비용 | 최신 산출물 + 호출 상한 내 `task_results` | 원문 파일·인덱스는 외부 보관. 과거 작업 payload 중복은 남아 있어 저장량 최적화 여지가 있음[^state-size] |
| 재개 / 복구 | `collected_tasks`, `task_errors`, `retry_counts`, 버전·입력 지문 | 이미 반영한 결과 중복 반영을 막고 일시적 오류를 재시도함[^state-recovery] |
| 동시 처리 | `task_results`의 `merge_task_results` reducer | B/C 병렬 결과를 작업·시도별 키로 병합하고 충돌을 거부함[^state-concurrency] |
| 종료 보장 | `attempts`, `limits`, `step_count`, `supervisor_count`, `stagnant_agents` | 성공 여부와 반복 예산을 분리하고 무진행·상한에서 종료함[^state-end] |

[^state-input]: A의 분류는 보고서 `INVESTMENT SNAPSHOT`에도 표시합니다. `report.classification`은 State의 기업/시장 분류에서 구성하며 G가 일치를 검사합니다.
[^state-payload]: 근거 본문 일부는 `Evidence`에 포함됩니다. State에 원문 파일을 넣지 않는다는 것이 모든 텍스트를 ID만으로 저장한다는 뜻은 아닙니다. `collect`는 최신 성공 연구 결과에서 활성 근거를 재구성합니다.
[^state-version]: `analysis_revision` 변경은 E/F/G 결과를, `report_revision` 변경은 G 결과를 무효화합니다. 차트·분류표·참고문헌도 최대 10쪽에 포함되며, 초과 시 F 축약 후 G 재평가를 합니다.
[^state-route]: **제출된 실행 트레이스와 코드로 확인합니다. Supervisor는 라우팅과 재작업 횟수·사유를 확인하는 것이 핵심입니다.** `supervisor` 이벤트의 `action`, `targets`, `reason`과 작업 이벤트의 `task_id`, `attempt`를 연결합니다. 최초 호출과 후속 재조사/재작성, 오류 재시도를 구분합니다. `supervisor_count`는 조정자 진입 횟수이고 `step_count`는 전체 실행 예산용이므로 재작업 수와 같지 않습니다.
[^state-trace]: 로컬 `events.jsonl` 및 선택적 LangSmith의 run/trace ID를 최종 `result.json`과 연결합니다. State의 현재 `next_action.reason`은 다음 실행에 필요한 정보이며 전체 결정 로그는 아닙니다. 테스트 통과와 실제 제출용 LangSmith 캡처 확보는 별도입니다. **현재 원격 실제 실행·제출용 캡처는 미완료입니다.**
[^state-size]: 호출 횟수는 제한하지만 직렬화된 State의 바이트 상한까지 보장하지 않습니다. 과거 상세 payload를 외부 저장하고 참조만 남기는 최적화는 아직 적용하지 않았습니다.
[^state-recovery]: `attempts`는 예약된 전체 시도, `retry_counts`는 오류 재시도 예약을 셉니다. 실제 완료 횟수는 task 결과/트레이스와 대조합니다. 체크포인트 재개 시 중단 당시 완료 여부를 모르는 외부 호출의 정확히 한 번 실행은 보장하지 않습니다.
[^state-concurrency]: **Orchestrator-Workers를 선택했다면 구조화된 plan과 그 결과에 따라 생성된 dynamic fan-out을 코드·트레이스로 입증해야 합니다.** 이 프로젝트는 Supervisor이므로 해당 패턴의 필수 항목은 비적용입니다. B/C 병렬 실행과 `Send` 사용만으로 Orchestrator의 dynamic fan-out 충족을 주장하지 않습니다.
[^state-end]: 기본 연구 에이전트별 3회, F/G 각 3회, Supervisor 20회, 전체 60회, 오류 6회입니다. 단계 수를 채웠다고 성공하지 않으며, 실제 PDF 최종 검사에서 재진입해도 예산을 초기화하지 않습니다.

### 제출 트레이스와 코드의 대조

| 확인할 장면 | 트레이스 증거 | 코드 / 검사 |
|---|---|---|
| State 기반 라우팅 | Supervisor의 대상·사유 → 작업 → collect → Supervisor | `agents/supervisor.py`, `graph/supervisor_workflow.py` |
| 문제별 재작업 | 부족 근거는 B/C/D, 작성 문제는 F 선택; 작업 attempt 증가 | `tests/graph/test_supervisor.py`의 재조사·형식 수정 검사 |
| 10쪽 초과 재진입 | `publication`의 rework/실제 쪽수 → F → G; 보고서 revision 증가 | `cli.py`, `test_late_pdf_overflow_returns_to_writer_and_judge_before_publication` |
| 반복 제한 / 성공 구분 | 예산 소진은 incomplete/failed, 품질 통과와 쪽수 충족 후 발행 | 동일 run의 result.json·체크포인트·최종 파일 대조 |

초기 B/C와 D 선택에는 정책상 고정 규칙이 남아 있습니다. 따라서 제출 설명에서는 모든 초기 라우팅을 LLM이 자유롭게 결정한다고 표현하지 않습니다. 실제 실행별 라우팅 수·재작업 수는 해당 제출 트레이스에서 집계하며, 테스트의 호출 횟수를 실제 모델 실행 결과로 대신 쓰지 않습니다.

실제 모델·State·reducer·재개 계약은 [인터페이스 계약](docs/contracts.md), 패턴과 단계별 설계 근거는 [구현 설계 20장](docs/implementation-design.md#20-multi-agent-orchestration-단계별-설계)을 따릅니다.

## Architecture

```mermaid
flowchart TD
    startNode([입력 검증]) --> supervisor{Supervisor}
    supervisor -->|기업 식별| agentA["A 기업·시장 분류"]
    supervisor -->|선택된 조사·재조사| agentB["B 기술 분석"]
    supervisor -->|선택된 조사·재조사| agentC["C 시장·이해관계자 분석"]
    supervisor -->|재무 보완| agentD["D 재무 분석"]
    supervisor -->|평가 정리| agentE["E 네 관점 정리"]
    supervisor -->|작성·수정| agentF["F 보고서 생성"]
    supervisor -->|품질 평가| agentG["G 별도 품질 평가"]
    agentA --> collectNode[결과 수집·State 갱신]
    agentB --> collectNode
    agentC --> collectNode
    agentD --> collectNode
    agentE --> collectNode
    agentF --> collectNode
    agentG --> collectNode
    collectNode --> supervisor
    supervisor -->|품질 통과| pageGate{최종 PDF 10쪽 이내}
    pageGate -->|통과| outputNode[최종 보고서 저장]
    pageGate -->|초과: 축약 지시 후 재평가| supervisor
    supervisor -->|수정 상한 도달| incompleteNode[incomplete 발행 보류]
    supervisor -->|재작업 소진 또는 복구 불가| incompleteNode
    incompleteNode --> diagnosticNode[실행 결과·오류·체크포인트만 저장]
    outputNode --> finishNode([END])
    diagnosticNode --> finishNode
```

화살표는 허용 경로이며 모든 에이전트를 매번 호출한다는 뜻은 아닙니다. 초기 B/C는 함께 조사할 수 있고, 시장 자료 부족은 C 재조사, 문장·인용 문제는 F 수정 후 G 재평가로 돌아갑니다. 분석 결과가 바뀌면 이전 E/F/G 결과를 무효화합니다.

## Directory Structure

현재 저장소의 실제 구조를 사용합니다. 자료·색인·보고서는 로컬 파일이며 커밋하지 않습니다.

```text
├── src/skala_rag/
│   ├── agents/                    # Supervisor, A~F 모듈, 별도 품질 평가 G
│   ├── graph/                     # 투자/Supervisor 그래프, 공유 State와 reducer
│   ├── models/                    # 기업·근거·요청·결과·오류·품질 모델
│   ├── ingestion/                 # 로컬 문서 로딩·청킹·임베딩·색인
│   ├── retrieval/                 # FAISS 검색과 SQLite 메타데이터
│   ├── runtime.py                 # 기존 조사 모듈과 모델의 연결
│   ├── tracing.py                 # 민감정보를 제외한 로컬/LangSmith 이벤트
│   ├── pdf_report.py              # PDF 보고서 렌더링
│   └── cli.py                     # orchestrate/analyze/report/index 진입점
├── scripts/                       # 기존 예시·검증·보고서 스크립트
├── tests/                         # 단위·통합·재개 테스트
├── docs/                          # 구현 설계와 인터페이스 계약
├── app.py                         # 직접 실행 진입점, 기본 Supervisor 경로
├── storage/                       # 실행 시 사용하는 로컬 저장 경로
│   ├── indexes/                   # 생성한 FAISS 색인
│   └── reports/<run_id>/           # 보고서·JSON·이벤트·SQLite 체크포인트
├── pyproject.toml
├── uv.lock
├── AGENTS.md
└── README.md
```

문서 풀은 `--research-root`로 지정합니다. 기업 마스터·출처 manifest·원문 자료를 가진 외부 자료조사 디렉터리를 사용하며 필요할 때 `storage/raw/`에 둘 수 있습니다. 프롬프트는 각 모듈에 있으므로 별도 `prompts/` 디렉터리는 만들지 않습니다.

## Usage

```bash
# 기본 환경 준비
uv sync --group dev
source .venv/bin/activate

# 실행 옵션 안내
python app.py

# 로컬 자료로 Supervisor 실행: API·의미 평가 모델 없이 동작 확인
python app.py \
  --query "로브로스의 기술 성숙도·시장·이해관계자·도메인 적용 평가" \
  --company 로브로스 --as-of-date 2026-09-30 \
  --research-root ../자료조사 --no-pdf

# GPT 모델과 LangSmith를 연결할 경우
uv sync --extra llm --group dev
# OPENAI_API_KEY, LANGSMITH_API_KEY를 환경변수로 설정합니다.
# GENERATION_MODEL, JUDGE_MODEL에는 사용 가능한 GPT 모델명을 설정합니다.
python app.py \
  --query "로브로스의 네 관점 중립 평가" \
  --company 로브로스 --as-of-date 2026-09-30 \
  --research-root ../자료조사 \
  --model "$GENERATION_MODEL" --judge-model "$JUDGE_MODEL" \
  --langsmith --langsmith-project skala-supervisor

# 출력 UUID로 재개: 자료·모델·검색·PDF·예산 옵션은 원래 실행과 동일하게 전달
python app.py --resume <run-UUID> \
  --research-root ../자료조사 \
  --model "$GENERATION_MODEL" --judge-model "$JUDGE_MODEL" \
  --langsmith --langsmith-project skala-supervisor

# 선택: 원문 자료를 FAISS 색인으로 구축
python app.py index build --source ../자료조사 --output storage/indexes/demo-v1
# orchestrate에 --retriever faiss --index storage/indexes/demo-v1을 추가해 사용

# 전체 검사: 재무 모듈 내부 테스트도 포함
uv run pytest -q
```

- `python app.py`는 실행 옵션을 보여 줍니다. 저장소의 `.venv`가 있으면 해당 Python으로 실행하므로 시스템 Python과 의존성이 섞이지 않습니다. `--query` 등 옵션을 전달하면 기본 `orchestrate` 경로를 실행하며, `analyze`/`report`/`index` 하위 명령도 그대로 사용할 수 있습니다. `uv run python app.py ...`로도 실행할 수 있습니다.
- 기본 검색은 지정한 storage에 FAISS 색인이 있으면 FAISS, 없으면 BM25입니다. 의미 모델 없이 실행한 결과는 내용 검증이 완료되지 않아 `incomplete`일 수 있습니다. `--financial-api`는 설정한 재무 API를 활성화합니다.
- PDF를 만들려면 한글 폰트가 필요하며 `SKALA_PDF_FONT`로 경로를 지정할 수 있습니다. `--no-pdf`는 PDF 생성과 쪽수 검사를 생략합니다.
- 결과는 `storage/reports/<run_id>/`의 `input.json`, `checkpoints.sqlite3`, `events.jsonl`, `result.json`, `report.md`, 선택적 `report.pdf`에 저장합니다. 보고서가 있더라도 최종 상태는 `result.json`으로 확인합니다.
- 종료 코드 0은 품질 통과·전송 오류 없음, 2는 미완료/실패/전송 오류, 1은 설정 오류입니다. 분석 상태와 LangSmith 전송 상태는 별도로 기록합니다.
- 실제 원격 모델 품질·LangSmith 대시보드 표시·제출용 trace 캡처는 별도 실행 검증 대상입니다. 로컬 테스트는 제어 분기·오류 복구·품질 수정·영속 재개를 검증합니다.
- 보고서 계약 v2 이전 실행은 새 run으로 다시 시작해야 합니다. CLI가 계약 버전을 설정 지문에 넣어 오래된 체크포인트 재개를 차단합니다.
- 기존 투자 분석은 `uv run skala-rag analyze --help`를 확인합니다. 개발·협업 규칙은 [AGENTS.md](AGENTS.md)를 따릅니다.


## 기존 storage의 벡터DB 연결

`--storage-root`는 외부에 옮겨 둔 저장소를 복사·재색인하지 않고 읽습니다. `indexes/qwen3-0.6b-v1`의 FAISS와 SQLite를 체크섬 검증하고, `raw` 아래 기업 마스터·출처 자료를 찾아 연결합니다. `models/hub`가 있으면 해당 로컬 Qwen 캐시를 사용하며 외부 모델 다운로드를 시도하지 않습니다. 모델 캐시가 불완전하면 오류가 나므로 전체 캐시를 준비해야 합니다.

```bash
python app.py --company 로브로스 \
  --query "로브로스 사업·기술·시장·경쟁·팀·재무와 위험 평가" \
  --as-of-date 2026-09-30 \
  --storage-root ./storage \
  --output storage/reports
```

생성·의미 평가 모델을 사용하려면 `--model`과 선택적 `--judge-model`을 별도로 지정합니다. 이 경우 검색된 자료가 모델 제공자에게 전달됩니다. 모델을 생략한 실행은 검색·연결 확인용 제한 보고이며 자동 의미 품질 통과 결과가 아닙니다. 위 명령은 현재 `26_AI_Agent/skala-rag-pipeline` 프로젝트 루트에서 실행하며 이 폴더의 `storage`를 읽습니다. 다른 위치에서는 실제 storage 경로를 지정합니다.

논문·특허의 `data/evidence_documents.jsonl`도 출처 목록에 합칩니다. 파일 경로와 제공된 해시를 검증하고 원문 URL·자료일·제목을 보존합니다. 연구 요약을 독립 검증된 원문으로 바꾸지 않습니다. Supervisor 경로에서는 기술 점수 계산의 근거 수 제한과 보고서용 검색 근거 보존을 분리합니다.


### 최종 발행과 선택적 재무 그래프

품질 미달 또는 해결 가능한 `unknown`은 담당자에게 재조사·수정을 요청한 뒤 다시 평가합니다. 핵심 근거 부족을 해소할 수 없거나 기업 분류가 미확정이면 작성 전에 종료합니다. `incomplete`/`failed`는 종료 상태이며 자동으로 무한 재시도하지 않습니다. 최종 Markdown/PDF는 `passed`이고 실제 PDF가 10쪽 이내일 때만 저장합니다. `--no-pdf`도 분량 검사는 수행하며 PDF 파일만 생략합니다. 미통과 초안은 진단용 result.json/체크포인트에만 남습니다.

`INVESTMENT SNAPSHOT`에 A의 기업 유형·공급 역할·산업·시장·고객·분류 상태·출처를 표시합니다. 작성 모델이 이 분류를 바꾸지 못하도록 코드에서 확정합니다.

재무 API가 동일 공시의 연간 당기·전기 수치와 단위·연결/별도 범위를 제공하면, `FINANCIALS` 본문 아래에 출처 표와 연도별 막대그래프를 넣습니다. 매출액·영업이익·총자산·총부채를 대상으로 하며, 반기/분기·단위 불명·단일 연도·상충 수치는 그래프를 생략합니다. 수치는 모델이 생성하지 않고 provider 근거에서 구성합니다. 그래프·분류표·참고문헌도 전체 10쪽에 포함됩니다. 현재 수집 계약은 평가 기업 단위이므로 검증된 경쟁사 비교 자료가 없을 때 경쟁사 재무 그래프는 제외합니다. 실제 API를 호출하지 않은 실행에서 그래프용 재무 수치가 확보됐다고 간주하지 않습니다.

최종 저장 직전 PDF가 10쪽을 초과해도 format 실패(실제 쪽수·축약 질문)를 현재 보고서 버전에 기록하고 동일 체크포인트에서 Supervisor → F → G로 복귀한다. 기존 attempts/step 예산을 초기화하지 않으며, 상한 소진 때만 incomplete로 종료한다.

### 현재 통합 작업 위치

현재 작업 기준은 `26_AI_Agent/skala-rag-pipeline`의 `codex/feat-agent-report-integrated` 브랜치입니다. `23_RAG` 사본에서 반영했던 보고서·검색·재무 차트·품질/축약 루프와 State 주석 커밋을 모두 포함합니다. 기존 로컬 storage는 그대로 읽고 Git에는 포함하지 않습니다. `skala-rag-pipeline-1` 및 `ai-service` 안의 저장소는 별도 사본이므로 이 브랜치의 작업 위치로 혼동하지 않습니다.

통합 점검: 최신 소스·테스트·설계 문서는 `02c82ab`와 일치하며, 현재 위치에 맞춰 실행 예시 경로만 갱신했습니다. 로컬 검증에서 FAISS 2,652개 벡터와 체크섬 등 6항목이 통과했습니다. 전체 테스트는 기존 Python 환경을 사용해 110 passed, 1 skipped, 25 subtests passed였습니다. 이 환경에서는 FAISS/PyTorch의 OpenMP 중복 로딩으로 기본 실행이 중단되어 테스트 프로세스에만 `KMP_DUPLICATE_LIB_OK=TRUE`를 적용했습니다. 이는 의존성 충돌의 임시 우회이며 프로젝트 기본 실행 코드에는 넣지 않았습니다. 실제 생성 모델·의미 평가·LangSmith 제출용 실행은 별도 미완료 항목입니다.
