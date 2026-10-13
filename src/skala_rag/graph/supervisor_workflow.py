"""Supervisor-mediated LangGraph with isolated workers and durable task outcomes."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import date
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import TypeAdapter

from skala_rag.agents.interfaces import OrchestrationAgents
from skala_rag.agents.supervisor import SupervisorPolicy, validate_decision
from skala_rag.graph.state import SupervisorState
from skala_rag.models.orchestration import (
    ClassificationPayload, ErrorInfo, EvaluationReport, EvaluationSummary, Limits,
    PerspectiveResult, QualityVerdict, ResearchResult, SupervisorDecision,
    TaskRequest, TaskResult, utc_now,
)
from skala_rag.tracing import safe_text

PAYLOADS = {'A': ClassificationPayload, 'B': ResearchResult, 'C': ResearchResult,
            'D': ResearchResult, 'E': EvaluationSummary, 'F': EvaluationReport, 'G': QualityVerdict}


def initial_state(query: str, as_of_date: str, *, company: str | None = None,
                  run_id: str | None = None, limits: Limits | None = None,
                  config_version: str = 'supervisor-v1', index_version: str | None = None) -> SupervisorState:
    date.fromisoformat(as_of_date)
    if not query.strip():
        raise ValueError('A nonempty query is required')
    run_id = str(UUID(run_id)) if run_id else str(uuid4())
    identity = {'query': query, 'company': company, 'as_of_date': as_of_date,
                'config_version': config_version, 'index_version': index_version}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return SupervisorState(run_id=run_id, thread_id=run_id, trace_id=run_id, schema_version='2',
        input_fingerprint=fingerprint, config_version=config_version, index_version=index_version,
        query=query, as_of_date=as_of_date,
        candidate_companies=[{'company_name': company}] if company else [],
        perspectives={}, evidence=[], active_evidence_ids=[], evaluation_summary=None,
        report=None, quality_result=None, task_results={}, collected_tasks=[], pending_tasks=[],
        task_status={}, attempts={}, stagnant_agents=[], research_sufficient=None,
        analysis_revision=0, report_revision=0,
        step_count=0, supervisor_count=0, limits=limits or Limits(), status='running',
        termination_reason=None, error_count=0, last_error=None, task_errors={}, retry_counts={})


def error_info(node, task_id, attempt, exc) -> ErrorInfo:
    # Exception messages may include HTTP request bodies or credentials. Record type,
    # safe fixed guidance, and a correlation ID instead of arbitrary exception text.
    name = type(exc).__name__
    retryable = isinstance(exc, (TimeoutError, ConnectionError)) or name in {
        'ReadTimeout', 'ConnectTimeout', 'ConnectError', 'RateLimitError', 'APIConnectionError', 'APITimeoutError'}
    status_code = getattr(exc, 'status_code', None)
    if isinstance(status_code, int) and (status_code == 429 or status_code >= 500):
        retryable = True
    message = '일시적 외부 호출 실패' if retryable else '작업 실행 또는 출력 계약 검증 실패'
    if name == 'ValidationError' and hasattr(exc, 'errors'):
        # Field paths/types only; never echo input values or model/source text.
        failures = exc.errors(include_input=False, include_url=False)[:5]
        message += ': ' + '; '.join('.'.join(str(part)[:50] for part in err['loc']) +
                                   ' (' + err['type'] + ')' for err in failures)
    return ErrorInfo(error_id=f'{task_id}:{attempt}:{name}', node=node, task_id=task_id,
        attempt=attempt, type=name, retryable=retryable,
        message=message)


def build_supervisor_graph(agents: OrchestrationAgents, *, checkpointer=None, recorder=None, interrupt_after=None):
    if set(agents.workers) != set('ABCDEFG'):
        raise ValueError('Workers A through G must be provided')
    policy = agents.supervise or SupervisorPolicy()

    def record(node, data, started_at=None):
        if recorder:
            recorder.record(node, data, started_at=started_at)

    def supervise(state: SupervisorState):
        started = utc_now()
        limits = state['limits']
        # Lifecycle budgets are enforced even for an injected/LLM policy.
        exhausted = (state['error_count'] >= limits.max_errors
            or state['supervisor_count'] >= limits.max_supervisor_steps
            or state['step_count'] + 4 > limits.max_steps)
        update = {'step_count': state['step_count'] + 1,
                  'supervisor_count': state['supervisor_count'] + 1}
        try:
            decision = (SupervisorDecision(action='finish', reason='실행 또는 오류 예산 소진',
                based_on_revision=state['analysis_revision'], terminal_status='incomplete' if state.get('report') else 'failed')
                if exhausted else SupervisorDecision.model_validate(policy(copy.deepcopy(state))))
            if decision.action in ('synthesize', 'write') and (decision.sufficient is False or state.get('research_sufficient') is False):
                decision = SupervisorDecision(action='finish', terminal_status='incomplete',
                    reason='근거 충분성 미충족; 작성 보류: ' + decision.reason,
                    sufficient=False, based_on_revision=state['analysis_revision'])
            validate_decision(decision, state)
        except Exception as exc:
            error = error_info('supervisor', state['run_id'] + ':supervisor', state['supervisor_count'] + 1, exc)
            # Invalid proposals get another coordinator turn, but remain bounded.
            errors = dict(state['task_errors'])
            errors[error.task_id] = error
            update.update(error_count=state['error_count'] + 1, last_error=error, task_errors=errors,
                next_action=SupervisorDecision(action='retry', reason='Supervisor 출력 검증 실패',
                    based_on_revision=state['analysis_revision']), pending_tasks=[])
            record('supervisor', {'status': 'failed', 'error_type': error.type}, started)
            return update
        errors = {k: e for k, e in state['task_errors'].items() if e.node != 'supervisor'}
        update.update(next_action=decision, task_errors=errors)
        if decision.sufficient is not None:
            update['research_sufficient'] = decision.sufficient
        if decision.action == 'finish':
            update.update(status=decision.terminal_status, termination_reason=decision.reason, pending_tasks=[])
        else:
            attempts, retries = dict(state['attempts']), dict(state['retry_counts'])
            tasks = []
            for agent in decision.targets:
                attempts[agent] = attempts.get(agent, 0) + 1
                task_id = f'{state["run_id"]}:{agent}'
                if decision.action == 'retry':
                    retries[task_id] = retries.get(task_id, 0) + 1
                tasks.append(TaskRequest(task_id=task_id, agent=agent, attempt=attempts[agent],
                    questions=decision.questions, reason=safe_text(decision.reason),
                    based_on_revision=state['analysis_revision']))
            update.update(pending_tasks=tasks, attempts=attempts, retry_counts=retries)
        record('supervisor', {'action': decision.action, 'targets': decision.targets,
            'reason': decision.reason, 'analysis_revision': state['analysis_revision'],
            'status': update.get('status', 'running')}, started)
        return update

    def dispatch(state):
        if state['status'] != 'running':
            return END
        if not state['pending_tasks']:
            return 'supervisor'
        return [Send(task.agent, {'request': task, 'snapshot': copy.deepcopy(state)})
                for task in state['pending_tasks']]

    def worker(packet):
        request = TaskRequest.model_validate(packet['request'])
        started = utc_now()
        try:
            payload = PAYLOADS[request.agent].model_validate(
                agents.workers[request.agent](request, copy.deepcopy(packet['snapshot'])))
            if isinstance(payload, (EvaluationSummary, EvaluationReport)) and payload.analysis_revision != request.based_on_revision:
                raise ValueError('Worker returned a stale analysis revision')
            if isinstance(payload, QualityVerdict) and payload.report_revision != packet['snapshot']['report_revision']:
                raise ValueError('Worker returned a stale report verdict')
            if isinstance(payload, ResearchResult):
                ids = {e.evidence_id for e in payload.evidence}
                for perspective in payload.perspectives:
                    if any(not set(c.evidence_ids).issubset(ids) for c in perspective.findings):
                        raise ValueError('Research cites evidence not returned by the task')
                profile = packet['snapshot']['company_profile']
                for e in payload.evidence:
                    if e.company_id is not None and e.company_id != profile.company_id:
                        raise ValueError('Evidence belongs to another company')
                    if e.published_at and e.published_at > profile.as_of_date:
                        raise ValueError('Evidence postdates the analysis cutoff')
                status = 'succeeded' if any(p.findings for p in payload.perspectives) else 'insufficient'
                if request.agent == 'D' and not payload.evidence:
                    status = 'unavailable'
            else:
                status = 'succeeded'
            result = TaskResult(request=request, status=status, payload=payload,
                started_at=started, completed_at=utc_now())
        except Exception as exc:
            result = TaskResult(request=request, status='failed',
                error=error_info(request.agent, request.task_id, request.attempt, exc),
                started_at=started, completed_at=utc_now())
        record(request.agent, {'task_id': request.task_id, 'attempt': request.attempt,
            'status': result.status, 'error_type': result.error.type if result.error else None,
            'evidence_ids': [e.evidence_id for e in result.payload.evidence]
                if isinstance(result.payload, ResearchResult) else []}, started)
        return {'task_results': {f'{request.task_id}:{request.attempt}': result}}

    def collect(state):
        consumed = set(state['collected_tasks'])
        fresh = [(key, result) for key, result in sorted(state['task_results'].items()) if key not in consumed]
        errors, statuses = dict(state['task_errors']), dict(state['task_status'])
        update = {'pending_tasks': [], 'step_count': state['step_count'] + len(fresh) + 1}
        errors_added = []
        stagnant = set(state['stagnant_agents'])
        research_changed = False
        for key, result in fresh:
            consumed.add(key)
            request, payload = result.request, result.payload
            statuses[request.task_id] = result.status
            if result.error:
                errors[request.task_id] = result.error
                errors_added.append(result.error)
                continue
            errors.pop(request.task_id, None)
            if isinstance(payload, ClassificationPayload):
                update.update(company_profile=payload.company_profile, market_category=payload.market_category,
                              current_company=payload.current_company or {})
            elif isinstance(payload, ResearchResult):
                previous = [r for k, r in state['task_results'].items() if k not in {key}
                    and r.request.agent == request.agent and r.request.attempt < request.attempt
                    and isinstance(r.payload, ResearchResult)]
                previous.sort(key=lambda r: r.request.attempt)
                if previous and previous[-1].payload == payload:
                    stagnant.add(request.agent)
                else:
                    stagnant.discard(request.agent)
                    research_changed = True
            elif isinstance(payload, EvaluationSummary):
                if payload.analysis_revision != state['analysis_revision']:
                    raise ValueError('Stale synthesis result')
                update['evaluation_summary'] = payload
                update['report'] = None
                update['quality_result'] = None
            elif isinstance(payload, EvaluationReport):
                if payload.analysis_revision != state['analysis_revision']:
                    raise ValueError('Stale report result')
                update.update(report=payload, quality_result=None, report_revision=state['report_revision'] + 1)
            elif isinstance(payload, QualityVerdict):
                if payload.report_revision != state['report_revision']:
                    raise ValueError('Stale quality verdict')
                update['quality_result'] = payload

        # Only latest successful attempt per agent is active; historical attempts
        # stay bounded by Limits and support idempotent checkpoint replay.
        latest = {}
        for result in state['task_results'].values():
            if isinstance(result.payload, ResearchResult):
                agent = result.request.agent
                if agent not in latest or latest[agent].request.attempt < result.request.attempt:
                    latest[agent] = result
        perspectives, evidence = {}, {}
        for agent in sorted(latest):
            for e in latest[agent].payload.evidence:
                if e.evidence_id in evidence and evidence[e.evidence_id] != e:
                    error = ErrorInfo(error_id=f'{state["run_id"]}:collect:{e.evidence_id}',
                        node='collect', task_id=state['run_id'] + ':collect', attempt=1,
                        type='EvidenceConflict', message='동일 근거 ID의 내용 충돌', retryable=False)
                    errors[error.task_id] = error
                    if not any(old.error_id == error.error_id for old in state['task_errors'].values()):
                        errors_added.append(error)
                    continue
                evidence[e.evidence_id] = e
            for p in latest[agent].payload.perspectives:
                if p.view not in perspectives:
                    perspectives[p.view] = p.model_copy(deep=True)
                else:
                    previous = perspectives[p.view]
                    findings = {json.dumps(c.model_dump(), sort_keys=True): c
                                for c in previous.findings + p.findings}
                    perspectives[p.view] = PerspectiveResult(view=p.view, findings=list(findings.values()),
                        missing_facts=previous.missing_facts + p.missing_facts)
        if research_changed:
            update.update(analysis_revision=state['analysis_revision'] + 1,
                          evaluation_summary=None, report=None, quality_result=None,
                          research_sufficient=None)
        update.update(perspectives=perspectives, evidence=list(evidence.values()),
            active_evidence_ids=list(evidence), collected_tasks=sorted(consumed),
            task_errors=errors, task_status=statuses, stagnant_agents=sorted(stagnant),
            error_count=state['error_count'] + len(errors_added),
            last_error=errors_added[-1] if errors_added else state['last_error'])
        record('collect', {'task_count': len(fresh), 'error_count': update['error_count'],
                          'analysis_revision': update.get('analysis_revision', state['analysis_revision'])})
        return update

    graph = StateGraph(SupervisorState)
    graph.add_node('supervisor', supervise)
    graph.add_node('collect', collect)
    graph.add_edge(START, 'supervisor')
    graph.add_conditional_edges('supervisor', dispatch, ['supervisor', END, *'ABCDEFG'])
    for agent in 'ABCDEFG':
        graph.add_node(agent, worker)
        graph.add_edge(agent, 'collect')
    graph.add_edge('collect', 'supervisor')
    return graph.compile(checkpointer=checkpointer, interrupt_after=interrupt_after, name='physical-ai-supervisor')


def supervisor_storage_payload(state: SupervisorState) -> dict:
    return TypeAdapter(SupervisorState).dump_python(state, mode='json')


def invoke_supervisor(graph, state, *, config=None):
    """Run or resume without automatically exporting full State/model prompts."""
    from langsmith import tracing_context
    with tracing_context(enabled=False):
        return graph.invoke(state, config=config)
