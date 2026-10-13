# 공통 개발 규칙

## 프로젝트와 기준 문서

이 저장소는 Physical AI 기업의 기술·시장·재무를 근거 기반으로 분석하고 투자 판단과 보고서를 생성하는 로컬 Python/LangGraph 프로젝트다. 실행 진입점은 CLI와 Python 함수이며, 웹 서버를 추가하는 작업은 별도 요구사항으로 다룬다.

작업 전 다음 문서를 확인한다.

- [README.md](README.md): 실행 방법과 현재 기능
- [구현 설계](docs/implementation-design.md): 설계 배경
- [인터페이스 계약](docs/contracts.md): 실제 타입, State, 검색 및 호출 계약

현재 동작은 코드와 테스트로 확인한다. 설계 문서의 예정 기능을 이미 구현된 기능으로 간주하지 않는다.

## 작업 시작과 수정 범위

1. 요구사항, 관련 코드·테스트, Git 상태를 먼저 확인한다. 기존 변경을 덮어쓰거나 되돌리지 않는다.
2. 병렬 개발 시 통합 담당자가 작업 지시에서 작업 ID, 담당자, 브랜치/worktree, 허용 경로, 선행 계약을 명시한 뒤 구현한다. 아래 역할 표는 기본 영역이며 실제 할당은 작업 지시를 따른다. 담당 영역을 위한 별도 문서를 만들지 않는다.
3. 등록된 범위의 파일만 수정한다. 단독 작업은 요청 범위를 담당 범위로 삼되, 여러 모듈에 걸친 작업은 수정 범위를 명시한다.
4. 파일 생성·수정 전 병렬 작업의 경로 중복을 확인한다. 겹치는 파일의 수정만 보류하고 통합 담당자와 조정하며, 독립적으로 진행 가능한 작업은 계속한다.
5. 불필요한 리팩터링, 대규모 포맷 변경, 요청과 무관한 의존성 추가를 피한다. 새 의존성이 필요하면 사유·대안·영향을 기록한다.

## 최소 구성 유지

- 새 코드·문서·스크립트·의존성은 기존 구성으로 해결할 수 없는 필요가 있을 때만 추가하고 이유를 설명한다. 예상 용도만으로 파일을 미리 만들지 않는다.
- 문서는 `README.md`(소개·실행), `AGENTS.md`(개발·담당 규칙), `docs/implementation-design.md`(설계), `docs/contracts.md`(모듈 연결 계약)를 기본으로 유지한다. 같은 내용을 여러 문서에 복제하지 않고 기준 문서를 링크한다.
- 문서는 코드에서 바로 확인되는 정의를 모두 나열하기보다 설계 이유, 연결 방법, 호환성 제약을 기록한다. 이미 문서화한 계약이 바뀌면 해당 문서도 갱신한다.
- 중복·낡은 문서는 고유한 유효 내용을 기준 문서로 옮긴 뒤 제거한다. 실행·발표·검증 목적이 다른 파일은 목적을 확인하고 판단한다.
- 파일 삭제·통합 전 import, CLI, 테스트, 문서 링크와 호출 관계를 확인한다. 관련 참조와 검증을 함께 갱신하며, 파일 수를 줄이려고 필요한 기능·테스트·설계 근거를 버리지 않는다.

## 기본 담당 영역

경로는 저장소 루트 기준이며 공통 파일 규칙이 우선한다. 새 문서·테스트도 작업 범위에 포함한다.

| 역할 | 기본 수정 영역 |
|---|---|
| A 시장 분류 | `src/skala_rag/agents/market_classification/` |
| B 기술 분석 | `src/skala_rag/agents/tech_agents/` |
| C 시장·경쟁 | `src/skala_rag/agents/market_competition/` |
| D 재무 분석 | `src/skala_rag/agents/financial_agent/`(내부 테스트 포함) |
| E 투자 판단 | `src/skala_rag/agents/decision_agents/` |
| 보고서 | `src/skala_rag/agents/report.py`, `src/skala_rag/pdf_report.py` |
| Retrieval / Ingestion | `src/skala_rag/retrieval/`, `src/skala_rag/ingestion/`의 공통 파일 제외 |
| 통합 | 아래 공통 파일, 할당된 통합 테스트·스크립트·문서 |

역할별 관련 테스트를 함께 할당하되 `tests/agents/test_b_e.py`처럼 공동 사용되는 파일은 한 담당자만 수정한다. 필요한 공통 변경은 대상 경로·이유·입출력 변화·호환성·검증 방법을 통합 담당자에게 전달한다. 선행 계약은 합의된 타입과 fixture를 사용하며 실제 통합 검증 전에는 완료로 보고하지 않는다. 통합 담당자가 선행 관계에 따라 병합하고 전체 검사를 확인한다.

## 공통 파일과 인터페이스

다음 경로는 통합 담당자가 관리한다. 일반 영역 작업자는 변경 필요 사항과 호환성 영향을 전달하고, 통합 담당자가 직접 반영하거나 해당 작업에 명시적으로 할당한다.

- `AGENTS.md`, `docs/contracts.md`
- `pyproject.toml`, `uv.lock`, `.github/`
- `src/skala_rag/models/`, `src/skala_rag/agents/interfaces.py`
- `src/skala_rag/graph/` 전체(State, reducer, 그래프 연결)
- `src/skala_rag/runtime.py`, `src/skala_rag/cli.py`
- `src/skala_rag/retrieval/models.py`, `src/skala_rag/retrieval/adapters.py`
- 패키지 공개 export를 바꾸는 `__init__.py`, 공통 실행·검증 스크립트

호출 시그니처, State 키, 모델 필드, evidence ID 의미, 검색 필터를 임의로 변경하지 않는다. 계약 변경은 영향을 받는 담당자와 합의하고 코드·문서·관련 테스트를 함께 갱신한다. 사용자 요청에서 이미 승인된 범위는 다시 승인받을 필요가 없다. 통합 담당자가 없는 단독 작업에서는 현재 작업자가 그 역할을 맡는다.

## 근거와 병렬 실행

- 분석 결과의 출처 ID·원문 URL·자료 시점을 보존한다. 근거가 없는 사실·수치·점수를 만들어 채우지 않고 `MissingFact`와 해당 상태로 표시한다.
- 입력 State, 전달받은 모델과 리스트를 직접 변경하지 않는다. 노드는 자신이 담당하는 키의 새 부분 업데이트를 반환한다.
- 기술·시장 병렬 노드는 각자 분석 결과와 `evidence`만 갱신한다. evidence 병합 규칙은 `docs/contracts.md`를 따른다.
- Context 구성과 RAG 평가는 현재 각 모듈 내부에 있다. 별도 공통 모듈 추출은 계약과 담당 경로를 먼저 정한 뒤 진행한다.
- API/LLM 오류를 성공한 분석으로 숨기지 않는다. 기준일·자료 부족·분류 검토 경로를 유지한다.
- `.env`·API 키·로컬 원문·모델·인덱스·생성 보고서를 커밋하지 않는다.

## Git와 작업 디렉터리

- 병렬 Codex 세션은 각자 별도 브랜치와 worktree를 사용한다. 같은 checkout에서 브랜치 전환·reset·stash를 공유하지 않는다.
- 새 브랜치 기본 형식은 `codex/<type>-<scope>-<description>`이다. 예: `codex/feat-retrieval-hybrid-search`, `codex/docs-agent-rules`. 사용자가 지정한 이름이나 이미 할당된 브랜치는 유지한다.
- 작업용 worktree는 저장소 밖 형제 경로에 둔다. 예: `git worktree add ../skala-rag-retrieval -b codex/feat-retrieval-hybrid-search <base-ref>`. `<base-ref>`는 작업에서 합의한 실제 기준 브랜치/커밋으로 대체한다.
- `main`에 직접 커밋·push하지 않고 PR로 통합한다. 커밋·push·PR 생성은 요청된 전달 범위에 맞춰 수행한다.
- 커밋과 PR 제목은 `<type>(<scope>): <summary>` 형식을 사용한다. type: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.
- 다른 작업자의 변경을 포함하지 않는다. 충돌은 base/양쪽 변경 의도를 확인하고 담당자와 조정한다. 한쪽 파일을 통째로 선택하거나 다른 사람의 변경을 버리는 방식으로 해결하지 않는다.
- worktree만으로 병합 충돌을 막을 수는 없다. 파일 소유권과 계약 조정을 함께 적용한다.

## 검증과 완료 기준

- 환경 준비: `uv sync --group dev`.
- 코드 변경은 관련 테스트를 실행한다. 통합·공통 계약 변경은 전체 `uv run pytest -q`를 실행한다. 재무 테스트는 `src/skala_rag/agents/financial_agent/tests/`에도 있으므로 누락하지 않는다.
- 문서만 바꾸면 경로·링크·실제 계약 일치와 `git diff --check`를 확인한다. 불필요한 테스트를 새로 만들지 않는다.
- 테스트 실패는 기존 실패인지 변경으로 발생했는지 확인한다. 실행하지 못한 검사는 이유를 기록하고 통과했다고 보고하지 않는다.
- 인덱스·환경 검증이 필요한 작업에는 `uv run python scripts/verify_repository.py`를 사용한다. 로컬 데이터와 실행 비용을 고려해 범위를 정한다.
- 계약 변경 테스트는 정상 경로 외에 관련 분류 검토, 빈 검색, 근거 병합, 결측값 또는 저장 변환의 실제 회귀 위험을 확인한다.

완료 보고에는 수정 파일, 검증 명령·결과, 인터페이스와 타 모듈 영향, 선행 작업 및 남은 문제를 포함한다. 요구사항 구현·범위 준수·관련 검사·호환성 확인을 마친 뒤, PR을 만드는 작업이면 [.github/pull_request_template.md](.github/pull_request_template.md)를 채운다. 병합 전 필수 검사와 관련 담당자 검토를 완료한다.
