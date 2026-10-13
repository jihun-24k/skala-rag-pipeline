"""기존 투자평가와 현재 Supervisor 과제의 공유 상태 계약.

State는 실행 도중 노드 사이에 전달하는 작업판이다. 이 파일은 저장할 값과
병합 규칙을 정의하고, 실제 분기·갱신은 workflow.py / supervisor_workflow.py가 한다.

현재 과제 흐름:
  입력 초기화 → Supervisor → 선택된 A~G → task_results → reducer → collect
  → 최신 State를 본 Supervisor가 재조사 / 작성 / 평가 / 종료를 선택한다.
  보고서 10쪽 초과 → format 실패 → Supervisor → F 축약 → G 재평가.

작업자는 State 복사본을 읽고 task_results만 반환한다. collect가 산출물·오류를
반영하며 Supervisor가 작업을 예약한다. 전체 결정 이력은 외부 트레이스에 둔다.
설계 근거·각주와 제출 증거: README.md의 State Schema.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import TypeAdapter
from typing_extensions import NotRequired, TypedDict

from skala_rag.models.orchestration import (
    ErrorInfo, EvaluationReport, EvaluationSummary, Limits, PerspectiveResult,
    QualityVerdict, RunStatus, SupervisorDecision, TaskRequest, TaskResult,
)

from skala_rag.models import (
    CompanyProfile,
    CompetitorAnalysis,
    Evidence,
    FinancialAssessment,
    InvestmentDecision,
    InvestmentReport,
    MarketAssessment,
    MarketCategory,
    ScoreDetail,
    TechAssessment,
)


def merge_evidence(current: list[Evidence], update: list[Evidence]) -> list[Evidence]:
    """기존 투자평가 B/C의 병렬 근거를 ID로 합치고 최초 내용을 보존한다.

    같은 ID의 다른 내용도 덮어쓰지 않는다. 현재 Supervisor 경로의 근거 충돌
    검사는 이 함수가 아니라 collect에서 수행한다.
    """

    merged: dict[str, Evidence] = {item.evidence_id: item for item in current}
    for item in update:
        merged.setdefault(item.evidence_id, item)
    return list(merged.values())


class InvestmentInput(TypedDict):
    """기존 analyze 경로의 사용자 입력. 기업 후보 중 현재 대상을 선택한다."""
    query: NotRequired[str]
    as_of_date: str
    candidate_companies: NotRequired[list[str | dict[str, object]]]
    current_index: NotRequired[int]


class InvestmentState(InvestmentInput, total=False):
    """기존 순차·병렬 투자평가 경로. 현재 Supervisor 과제와 별도 계약이다.

    A 분류 → B 기술/C 시장 병렬 → D 재무 → E 투자 판단 → 보고서.
    초기에는 없는 결과 필드가 각 노드 실행 후 채워지므로 total=False이다.
    """
    current_company: dict[str, object]  # A가 선택한 기업 입력 정보.
    company_profile: CompanyProfile  # A의 기업 식별·유형·기준일; 후속 분석의 대상.
    market_category: MarketCategory  # A의 산업·시장 분류; 조사 범위를 결정.
    tech_analysis: TechAssessment  # B가 반환한 기술 분석.
    market_analysis: MarketAssessment  # C가 반환한 시장 분석.
    competitor_analysis: CompetitorAnalysis  # C가 반환한 경쟁 구도.
    financial_analysis: FinancialAssessment  # D의 확인된 수치와 결측.
    evidence: Annotated[list[Evidence], merge_evidence]  # B/C 동시 쓰기를 reducer로 병합.
    decision: InvestmentDecision  # E의 투자 판단; 보고서 작성 입력.
    scores: dict[str, ScoreDetail]  # 판단에 사용한 근거 기반 점수.
    report: InvestmentReport  # 분석과 판단을 기존 양식으로 작성한 결과.

class InvestmentOutput(TypedDict):
    """기존 경로가 종료 후 반환하는 결과. 저장 전 아래 TypeAdapter로 검증한다."""
    current_company: NotRequired[dict[str, object]]
    company_profile: CompanyProfile
    market_category: MarketCategory
    tech_analysis: TechAssessment
    market_analysis: MarketAssessment
    competitor_analysis: CompetitorAnalysis
    financial_analysis: FinancialAssessment
    evidence: list[Evidence]
    decision: InvestmentDecision
    scores: dict[str, ScoreDetail]
    report: InvestmentReport


_output_adapter = TypeAdapter(InvestmentOutput)


def to_storage_payload(output: InvestmentOutput) -> dict[str, Any]:
    """그래프 결과를 JSON 호환 값으로 검증·변환해 저장 계층에 넘긴다.

    날짜는 ISO 문자열로 바뀌고 Pydantic 모델은 일반 dict가 된다. 이 함수는
    DB 연결이나 INSERT를 하지 않는다. 호출자가 이후 저장 여부를 결정한다.
    """
    validated = _output_adapter.validate_python(output)
    return _output_adapter.dump_python(validated, mode="json")


def merge_task_results(current: dict[str, TaskResult], update: dict[str, TaskResult]) -> dict[str, TaskResult]:
    """Supervisor 작업자들이 동시에 반환한 결과를 합친다.

    키는 <task_id>:<attempt>. 동일 결과 재전달은 허용하지만 같은 키에 다른
    결과가 들어오면 오류다. 입력 dict를 수정하지 않고 새 dict를 반환한다.
    collect는 collected_tasks를 이용해 각 결과를 한 번만 반영한다.
    """
    merged = dict(current)
    for key, result in update.items():
        if key in merged and merged[key] != result:
            raise ValueError(f'Conflicting result for task attempt {key}')
        merged[key] = result
    return merged


class SupervisorState(TypedDict, total=False):
    """현재 orchestrate 경로의 실행별 공유 State; 에이전트별 State가 아니다.

    initial_state()가 제어 필드를 초기화하고 A 실행 후 기업 필드가 채워진다.
    TypedDict는 필드 계약이며 payload 검증은 노드 경계의 Pydantic 모델이 담당한다.
    아래 주석은 생성/갱신 주체와 다음 단계의 사용 목적을 설명한다.
    """

    # 1. 실행 식별·재개: 초기화/CLI가 설정. 체크포인트와 트레이스를 연결한다.
    run_id: str  # 평가 실행 UUID; 작업 ID와 결과 디렉터리의 기준.
    thread_id: str  # 같은 실행의 SQLite 체크포인트를 찾는 키.
    trace_id: str  # 외부 events/LangSmith와 State를 연결하는 키.
    schema_version: str  # State 계약 버전; 이전 체크포인트와 구분.
    input_fingerprint: str  # 입력 지문; CLI는 재개 시 설정·자료 지문도 대조.
    config_version: str  # 실행 설정 버전; 바뀐 조건으로 과거 실행 재개 방지.
    index_version: str | None  # 검색 자료/인덱스 식별; 자료 변경 확인용.

    # 2. 조사 범위: 사용자 입력 → A 분류 결과 → B/C/D 및 작성자의 입력.
    query: str  # 요청 원문; B/C 검색에는 이번 재조사 질문을 추가한다.
    as_of_date: str  # 평가 기준일; 미래 자료를 근거로 사용하지 않도록 제한.
    candidate_companies: list[str | dict[str, object]]  # A가 식별할 기업 후보.
    company_profile: CompanyProfile  # collect가 A 결과 반영; 평가 기업·유형 확정.
    market_category: MarketCategory  # collect가 A 결과 반영; 시장·고객·분류 검토 여부.
    current_company: dict[str, object]  # A의 부가 기업 입력 정보.

    # 3. 최신 산출물: collect가 갱신. 원문 파일/인덱스는 외부에 보관한다.
    perspectives: dict[str, PerspectiveResult]  # 최신 B/C/D 주장을 관점별로 합친 분석.
    evidence: list[Evidence]  # 해당 분석의 근거 발췌·출처·수치; 전체 원문 파일은 아님.
    active_evidence_ids: list[str]  # 현재 근거 ID; 과거 시도의 대체된 근거와 구분.
    evaluation_summary: EvaluationSummary | None  # E의 종합; 근거 변경 시 None으로 무효화.
    report: EvaluationReport | None  # F의 초안·근거별 사업성 점수·커버리지; 존재만으로 발행 허용 안 함.
    quality_result: QualityVerdict | None  # G의 현재 보고서 판정; 수정 시 이전 판정 폐기.

    # 4. 작업 전달: Supervisor 예약 → 작업자 결과 → reducer → collect 순서.
    task_results: Annotated[dict[str, TaskResult], merge_task_results]  # 작업자의 유일한 쓰기 필드.
    collected_tasks: list[str]  # collect가 이미 반영한 결과 키; 재개 시 중복 반영 방지.
    pending_tasks: list[TaskRequest]  # Supervisor의 담당자·질문·시도 번호; dispatch가 실행.
    task_status: dict[str, str]  # collect가 기록한 작업별 최신 성공/부족/불가/실패 상태.
    next_action: SupervisorDecision  # Supervisor의 현재 대상·선택 이유·종료 판단.
    attempts: dict[str, int]  # Supervisor가 예약한 agent별 총 시도 수; 최초 호출 포함.
    stagnant_agents: list[str]  # collect가 동일 결과 반복을 감지; 무의미한 재조사 차단.
    research_sufficient: bool | None  # 충분성 판단; False면 E/F 진입 차단, 새 연구 시 초기화.

    # 5. 최신성: 새 근거가 나왔는데 예전 보고서/통과 판정을 쓰는 문제를 방지.
    analysis_revision: int  # collect가 연구 변경 시 증가하고 E/F/G 결과를 무효화.
    report_revision: int  # collect가 F 결과 반영 시 증가; G는 이 버전과 일치해야 함.

    # 6. 반복·종료: 횟수는 안전 상한이지 성공 기준이 아니다.
    step_count: int  # Supervisor·작업 결과·collect의 실행 예산용 누적 수.
    supervisor_count: int  # Supervisor 진입 횟수; 재작업 횟수와 같지 않음.
    limits: Limits  # 연구/작성/평가/전체 단계/오류 상한; 축약 재진입 시에도 유지.
    status: RunStatus  # running 중 재작업; passed/incomplete/failed/interrupted는 종료 상태.
    termination_reason: str | None  # 왜 종료했는지; 상한 소진을 성공으로 표시하지 않음.

    # 7. 오류 복구: 실행 실패와 자료 부족을 구분하고 일시적 오류만 재시도한다.
    error_count: int  # 최초 수집한 오류의 누적 수; 복구 성공해도 감소하지 않음.
    last_error: ErrorInfo | None  # 마지막 오류 기록; 남아 있다고 미해결이라는 뜻은 아님.
    task_errors: dict[str, ErrorInfo]  # 현재 미해결 오류; 같은 작업 성공 시 collect가 제거.
    retry_counts: dict[str, int]  # 오류 재시도 예약 수; 품질 개선 재작업은 attempts로 확인.

    # 제출 증거: supervisor 이벤트의 action/targets/reason과 작업 attempt를 연결해
    # 라우팅·재조사·재작성·오류 retry를 구분한다. 전체 결정 이력은 외부 trace에 둔다.
    # 과거 task_results의 상세 payload는 상한 내 보존하나 byte 크기 제한은 아직 없다.
    # Orchestrator-Workers의 plan/dynamic fan-out은 본 Supervisor 선택의 필수 항목이 아님.
