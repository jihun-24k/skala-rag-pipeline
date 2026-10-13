"""State-driven routing with explicit gates and bounded rework."""
from __future__ import annotations

from skala_rag.models.orchestration import Limits, SupervisorDecision, VIEWS

OWNER = {'technology': 'B', 'market': 'C', 'stakeholders': 'C', 'domain': 'B'}
QUESTIONS = {
    'A': '기업 동일성, 제품 형태와 적용 분야를 확인하세요.',
    'B': '핵심 기술·제품과 실제 적용 조건, 시험 한계·반대 근거, 창업자·핵심 기술인력의 검증된 역할을 조사하세요.',
    'C': '사업 아이디어·수익모델, 시장 규모·범위, 경쟁사·기존 대안, 유료 고객·계약과 PoC의 차이, 고객 요구와 출처 성격을 정리하고 확보 가능한 반대 근거도 확인하세요. 독립 검증 자료는 필수 조건이 아닙니다.',
    'D': '기준일에 이용 가능한 재무자료와 사업 지속성의 불확실성을 확인하세요.',
    'E': '네 관점의 근거와 한계를 중립적으로 정리하세요.',
    'F': '평가 정리를 사용해 근거 ID가 연결된 중립적인 보고서를 작성하세요.',
    'G': '근거 연결성·중립성·편향을 평가하고 기존 목차·SUMMARY 반 페이지·최대 10쪽 형식을 확인하세요.',
}


def classification_unresolved(state) -> bool:
    profile, category = state.get('company_profile'), state.get('market_category')
    unknown = {'', '미확정', '미확인', '분류 검토 필요', 'unknown', 'unclassified'}
    return bool(profile and category and (category.review_required
        or profile.physical_ai_type.strip().casefold() in unknown
        or category.sub_industry.strip().casefold() in unknown))


def available(state, agent) -> bool:
    limits: Limits = state['limits']
    maximum = limits.max_report_attempts if agent in ('F', 'G') else (
        limits.max_supervisor_steps if agent == 'E' else limits.max_attempts_per_agent)
    return state['attempts'].get(agent, 0) < maximum


class SupervisorPolicy:
    def __call__(self, state) -> SupervisorDecision:
        revision = state['analysis_revision']

        def choose(action, targets=(), reason='', questions=(), status=None):
            return SupervisorDecision(action=action, targets=list(targets), reason=reason,
                questions=list(questions) or [QUESTIONS[a] for a in targets],
                based_on_revision=revision, terminal_status=status)

        def stop(reason, failed=False):
            return choose('finish', reason=reason, status='failed' if failed else 'incomplete')

        limits = state['limits']
        if state['error_count'] >= limits.max_errors:
            return stop('오류 예산 소진', not bool(state.get('report')))
        if state['supervisor_count'] >= limits.max_supervisor_steps or state['step_count'] >= limits.max_steps:
            return stop('실행 상한 도달', not bool(state.get('report')))

        for error in state['task_errors'].values():
            agent = error.node
            if agent == 'supervisor':
                continue
            if error.retryable and available(state, agent):
                return choose('retry', [agent], '일시적 실행 오류 재시도', [QUESTIONS[agent]])
            if agent not in ('B', 'C', 'D'):
                return stop('필수 작업 실패 또는 재시도 상한 도달', not bool(state.get('report')))

        if not state.get('company_profile'):
            return choose('research', ['A'], '기업 식별이 선행되어야 함')

        unresolved = classification_unresolved(state)
        if unresolved:
            return stop('기업 식별·분류 확인 필요; 보고서 작성 보류')
        if not unresolved:
            initial = [agent for agent in ('B', 'C') if not state['attempts'].get(agent)]
            if initial:
                return choose('research', initial, '미조사 관점 확인')
            if not state['attempts'].get('D'):
                return choose('research', ['D'], '사업 지속성 자료 확인')

        report = state.get('report')
        quality = state.get('quality_result')
        current_quality = quality and quality.report_revision == state['report_revision']
        if current_quality and report and report.analysis_revision == revision:
            if quality.passed and not state['task_errors'] and not unresolved and state.get('research_sufficient') is not False:
                return choose('finish', reason='세 품질 기준·보고서 형식·필수 작업 통과', status='passed')
            for issue in quality.items:
                target = issue.target
                if issue.verdict in ('fail', 'unknown') and target and available(state, target):
                    if target in ('B', 'C', 'D') and (unresolved or target in state['stagnant_agents']):
                        continue
                    if target in ('B', 'C', 'D') and any(e.node == target and not e.retryable
                                                         for e in state['task_errors'].values()):
                        continue
                    action = 'research' if target in ('B', 'C', 'D') else 'write' if target == 'F' else 'synthesize'
                    return choose(action, [target], issue.reason, issue.questions or [QUESTIONS[target]])
            return stop('품질 미달 또는 의미 평가 확인 불가; 재작업 가능 경로 소진')

        # Missing optional perspectives are report limitations, not automatic rework.
        supported = {e.evidence_id for e in state['evidence']}
        has_facts = any(c.evidence_ids and set(c.evidence_ids).issubset(supported)
                        for p in state['perspectives'].values() for c in p.findings)
        if not unresolved and not has_facts:
            gaps = [view for view in VIEWS if not state['perspectives'].get(view)
                    or not state['perspectives'][view].findings]
            targets = list(dict.fromkeys(OWNER[v] for v in gaps))
            targets = [a for a in targets if available(state, a) and a not in state['stagnant_agents']
                       and not any(e.node == a and not e.retryable for e in state['task_errors'].values())]
            if targets:
                return choose('research', targets, '관점별 핵심 근거 부족',
                              [f'{view} 관점의 확인되지 않은 질문을 다른 출처와 구체적인 적용 사례로 조사하세요.'
                               for view in gaps])

        if not has_facts and not state['task_errors']:
            return stop('출처에 연결된 사실이 없어 제한 보고서도 작성할 수 없음')

        if state.get('research_sufficient') is False:
            return stop('핵심 근거 충분성 미충족; 재조사 후에도 해소되지 않아 작성 보류')
        if state['task_errors']:
            return stop('해결되지 않은 조사 오류; 작성 보류', failed=True)

        summary = state.get('evaluation_summary')
        if summary is None or summary.analysis_revision != revision:
            return choose('synthesize', ['E'], '현재 분석 버전의 평가 정리 필요')
        if report is None or report.analysis_revision != revision:
            if available(state, 'F'):
                return choose('write', ['F'], '최신 평가 정리로 보고서 작성')
            return stop('보고서 작성 예산 소진')
        if not current_quality:
            if available(state, 'G'):
                return choose('evaluate', ['G'], '새 보고서의 품질 평가 필요')
            return stop('품질 평가 예산 소진')
        return stop('진행 가능한 작업 없음')


def validate_decision(decision: SupervisorDecision, state):
    """A policy/model proposes a route; code enforces lifecycle and budgets."""
    if decision.based_on_revision != state['analysis_revision']:
        raise ValueError('Supervisor used a stale analysis revision')
    if len(decision.targets) != len(set(decision.targets)):
        raise ValueError('Duplicate worker targets')
    allowed = {'research': {'A', 'B', 'C', 'D'}, 'retry': set('ABCDEFG'),
               'synthesize': {'E'}, 'write': {'F'}, 'evaluate': {'G'}, 'finish': set()}
    if not set(decision.targets).issubset(allowed[decision.action]):
        raise ValueError('Action and worker targets disagree')
    if decision.action != 'finish' and not decision.targets:
        raise ValueError('Non-terminal route requires workers')
    if decision.action == 'finish':
        if decision.terminal_status is None:
            raise ValueError('Finish requires a terminal status')
        if decision.terminal_status == 'passed':
            quality, report = state.get('quality_result'), state.get('report')
            if not (quality and report and quality.passed and not state['task_errors']
                    and not classification_unresolved(state)
                    and state.get('research_sufficient') is not False
                    and report.analysis_revision == state['analysis_revision']
                    and quality.report_revision == state['report_revision']):
                raise ValueError('Cannot finish as passed without current, successful quality evaluation')
        return
    if decision.terminal_status is not None:
        raise ValueError('Non-terminal decision cannot set terminal status')
    limits = state['limits']
    if (state['error_count'] >= limits.max_errors or state['step_count'] + len(decision.targets) + 2 > limits.max_steps
            or state['supervisor_count'] >= limits.max_supervisor_steps):
        raise ValueError('Execution budget exhausted')
    for agent in decision.targets:
        if not available(state, agent):
            raise ValueError('Worker attempt budget exhausted')
        if agent != 'A' and not state.get('company_profile'):
            raise ValueError('Classification must precede worker execution')
        if agent in ('B', 'C', 'D') and classification_unresolved(state):
            raise ValueError('Cannot research an unresolved identity')
        if agent == 'A' and state.get('company_profile'):
            raise ValueError('Cannot replace an established company identity')
        if decision.action == 'retry' and not any(e.node == agent and e.retryable
                                                  for e in state['task_errors'].values()):
            raise ValueError('Retry requires a retryable task error')
        if agent in ('E', 'F') and (state.get('research_sufficient') is False or decision.sufficient is False):
            raise ValueError('Insufficient research cannot enter synthesis or writing')
        if agent == 'E' and not classification_unresolved(state) and not all(state['attempts'].get(a) for a in ('B', 'C')):
            raise ValueError('Synthesis cannot precede research')
        if agent == 'F':
            summary = state.get('evaluation_summary')
            if not summary or summary.analysis_revision != state['analysis_revision']:
                raise ValueError('Report writing requires current synthesis')
        if agent == 'G':
            report = state.get('report')
            if not report or report.analysis_revision != state['analysis_revision']:
                raise ValueError('Quality evaluation requires a current report')
