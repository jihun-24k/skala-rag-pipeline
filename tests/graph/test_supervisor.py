from collections import Counter
from datetime import date

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from skala_rag.agents.interfaces import OrchestrationAgents
from skala_rag.agents.report_evaluation import ReportEvaluator
from skala_rag.graph.supervisor_workflow import build_supervisor_graph, initial_state, supervisor_storage_payload
from skala_rag.models import CompanyProfile, Evidence, MarketCategory
from skala_rag.models.orchestration import (
    ClassificationPayload, CitedClaim, EvaluationReport, EvaluationSummary, Limits,
    PerspectiveResult, QualityItem, QualityVerdict, ResearchResult, SupervisorDecision, VIEWS,
)


def researchers(*, market_gap=False, timeout=False, wrong_reference=False, unresolved=False,
                no_judge=False, overrides=None, supervise=None):
    calls = []
    profile = CompanyProfile(company_id='robot', company_name='테스트 로봇',
        physical_ai_type='이동형 로봇', stage='검증', as_of_date=date(2026, 9, 30))
    tech = Evidence(evidence_id='tech', claim_text='시험 조건에서 제어 성능의 한계가 확인됨',
        stance='contradict', source_type='academic', source_grade='A',
        source_uri='https://university.example/paper', company_id='robot', independent=True)
    market = Evidence(evidence_id='market', claim_text='운영사가 현장 도입 조건을 공개함',
        stance='support', source_type='counterparty', source_grade='B',
        source_uri='https://customer.example/deployment', company_id='robot', independent=True)

    def perspective(view, e):
        return PerspectiveResult(view=view, findings=[CitedClaim(text=e.claim_text, evidence_ids=[e.evidence_id])])

    def a(task, state):
        return ClassificationPayload(company_profile=profile,
            market_category=MarketCategory(industry='로봇', sub_industry='이동형 로봇', review_required=unresolved))

    def b(task, state):
        return ResearchResult(perspectives=[perspective('technology', tech), perspective('domain', tech)], evidence=[tech])

    def c(task, state):
        if task.attempt == 1 and timeout:
            raise TimeoutError('token=sk-secret must never be exposed')
        if task.attempt == 1 and market_gap:
            return ResearchResult(perspectives=[PerspectiveResult(view='market'), PerspectiveResult(view='stakeholders')])
        return ResearchResult(perspectives=[perspective('market', market), perspective('stakeholders', market)], evidence=[market])

    def e(task, state):
        return EvaluationSummary(perspectives=[state['perspectives'].get(v, PerspectiveResult(view=v)) for v in VIEWS],
                                 analysis_revision=state['analysis_revision'])

    def f(task, state):
        refs = {e.evidence_id: e.source_uri for e in state['evidence']}
        if wrong_reference and task.attempt == 1:
            refs['tech'] = 'https://invented.example/'
        return EvaluationReport(summary='기업의 네 관점 평가',
            perspectives=state['evaluation_summary'].perspectives,
            references=refs, analysis_revision=state['analysis_revision'])

    def judge(report, state, task):
        return QualityVerdict(items=[QualityItem(criterion=k, verdict='pass', reason='fixture 의미 검증')
            for k in ('groundedness', 'neutrality', 'bias', 'coverage')], report_revision=state['report_revision'])

    workers = {'A': a, 'B': b, 'C': c, 'D': lambda task, state: ResearchResult(),
               'E': e, 'F': f, 'G': ReportEvaluator(None if no_judge else judge)}
    workers.update(overrides or {})
    def track(agent, callback):
        def invoke(task, state):
            calls.append((agent, task))
            return callback(task, state)
        return invoke
    return OrchestrationAgents(workers={k: track(k, v) for k, v in workers.items()}, supervise=supervise), calls


def run(agents, limits=None):
    return build_supervisor_graph(agents).invoke(initial_state('로봇 평가', '2026-09-30', limits=limits),
                                                config={'recursion_limit': 150})


def counts(calls):
    return Counter(a for a, task in calls)


def test_cli_saves_report_and_resumes_without_repeating_completed_tasks(tmp_path, monkeypatch):
    import json
    from uuid import uuid4
    import skala_rag.runtime as runtime
    from skala_rag.cli import _parser, _orchestrate_command
    from skala_rag.agents.market_classification.catalog import JsonCompanyCatalog
    import skala_rag.agents.market_competition.documents as documents

    agents, calls = researchers()
    monkeypatch.setattr(JsonCompanyCatalog, '__init__', lambda self, root: setattr(self, 'root', tmp_path))
    monkeypatch.setattr(JsonCompanyCatalog, 'list_companies', lambda self: [])
    monkeypatch.setattr(documents, 'load_documents', lambda root: [])
    monkeypatch.setattr(runtime, 'build_orchestration_agents', lambda **kwargs: agents)
    run_id = str(uuid4())
    common = ['orchestrate', '--output', str(tmp_path), '--no-pdf']
    args = _parser().parse_args(common + ['--query', 'fixture', '--run-id', run_id])
    assert _orchestrate_command(args) == 0
    run_dir = tmp_path / run_id
    payload = json.loads((run_dir / 'result.json').read_text())
    assert payload['status'] == 'passed' and payload['tracing']['delivery_status'] == 'disabled'
    assert (run_dir / 'report.md').read_text().startswith('# SUMMARY')
    assert (run_dir / 'checkpoints.sqlite3').is_file()
    old_count = len(calls)
    assert _orchestrate_command(_parser().parse_args(common + ['--resume', run_id])) == 0
    assert len(calls) == old_count
    with pytest.raises(ValueError, match='differs'):
        _orchestrate_command(_parser().parse_args(common + ['--resume', run_id, '--query', 'changed']))


def test_neutral_pdf_preserves_four_views_and_contains_no_investment_headings(tmp_path):
    from pypdf import PdfReader
    from skala_rag.pdf_report import render_evaluation_pdf
    agents, _ = researchers()
    report = run(agents)['report']
    path = render_evaluation_pdf(report, tmp_path / 'report.pdf')
    pages = PdfReader(str(path)).pages
    text = '\n'.join(page.extract_text() for page in pages)
    assert len(pages) <= 10
    assert 'SUMMARY' in text and '기술 성숙도' in text and '이해관계자' in text
    assert '투자 의견' not in text
    assert 'REFERENCE' in text


def test_parallel_failures_recover_independently_without_double_counting():
    base, _ = researchers()
    def timeout_once(agent):
        def invoke(task, state):
            if task.attempt == 1:
                raise TimeoutError('provider failed')
            return base.workers[agent](task, state)
        return invoke
    agents, calls = researchers(overrides={'B': timeout_once('B'), 'C': timeout_once('C')})
    state = run(agents)
    assert state['status'] == 'passed'
    assert state['error_count'] == 2 and not state['task_errors']
    assert counts(calls)['B'] == counts(calls)['C'] == 2
    assert sorted(state['retry_counts'].values()) == [1, 1]


def test_conflicting_evidence_id_is_a_collection_error():
    base, _ = researchers()
    def conflict(task, state):
        payload = base.workers['C'](task, state)
        payload.evidence[0].evidence_id = 'tech'
        for p in payload.perspectives:
            p.findings[0].evidence_ids = ['tech']
        return payload
    agents, _ = researchers(overrides={'C': conflict})
    state = run(agents)
    assert state['status'] == 'failed'
    assert state['error_count'] == 1 and state['last_error'].type == 'EvidenceConflict'


def test_semantic_judge_cannot_mask_wrong_report_revision():
    def judge(report, state, task):
        return QualityVerdict(items=[QualityItem(criterion=k, verdict='pass', reason='wrong version')
            for k in ('groundedness', 'neutrality', 'bias', 'coverage')],
            report_revision=state['report_revision'] + 1)
    agents, _ = researchers(overrides={'G': ReportEvaluator(judge)})
    state = run(agents)
    assert state['status'] == 'incomplete'
    assert state['last_error'].node == 'G' and state['quality_result'] is None


def test_runtime_adapter_uses_research_questions_and_keeps_offline_financial_limit(monkeypatch):
    from types import SimpleNamespace
    import skala_rag.runtime as runtime
    from skala_rag.agents.interfaces import AnalysisResult
    from skala_rag.models import TechAssessment
    from skala_rag.models.orchestration import TaskRequest
    base, _ = researchers()
    state = run(base)
    seen = []
    def technology(profile, category, query):
        seen.append(query)
        return AnalysisResult(TechAssessment(product_summary='시험'), [state['evidence'][0]])
    from skala_rag.agents.financial_agent.adapter import unavailable_financials
    monkeypatch.setattr(runtime, 'build_runtime_agents', lambda **kwargs: SimpleNamespace(
        analyze_technology=technology, analyze_financials=unavailable_financials))
    agents = runtime.build_orchestration_agents()
    request = TaskRequest(task_id='B', agent='B', attempt=2, questions=['새로운 적용 조건 확인'],
                          reason='자료 부족', based_on_revision=state['analysis_revision'])
    payload = agents.workers['B'](request, state)
    assert '새로운 적용 조건 확인' in seen[0]
    assert payload.perspectives[0].findings[0].evidence_ids == ['tech']
    financial = agents.workers['D'](request.model_copy(update={'agent': 'D'}), state)
    assert financial.perspectives[0].missing_facts and not financial.evidence


def test_python_runner_disables_automatic_tracing_inside_parallel_workers(monkeypatch):
    from langsmith.run_helpers import get_tracing_context
    from skala_rag.graph import invoke_supervisor
    monkeypatch.setenv('LANGSMITH_TRACING', 'true')
    base, _ = researchers()
    def technology(task, state):
        assert get_tracing_context()['enabled'] is False
        return base.workers['B'](task, state)
    agents, _ = researchers(overrides={'B': technology})
    state = invoke_supervisor(build_supervisor_graph(agents), initial_state('fixture', '2026-09-30'),
                              config={'recursion_limit': 150})
    assert state['status'] == 'passed'


def test_good_report_runs_separate_quality_node_and_finishes():
    agents, calls = researchers()
    state = run(agents)
    assert state['status'] == 'passed'
    assert counts(calls) == Counter(dict(A=1, B=1, C=1, D=1, E=1, F=1, G=1))
    assert state['active_evidence_ids'] == ['tech', 'market']
    assert state['quality_result'].passed
    assert state['report'].analysis_revision == state['analysis_revision']
    assert supervisor_storage_payload(state)['task_results']


def test_only_missing_market_is_researched_again_with_new_question():
    agents, calls = researchers(market_gap=True)
    state = run(agents)
    assert state['status'] == 'passed'
    assert counts(calls)['C'] == 2 and counts(calls)['B'] == 1
    requests = [task for agent, task in calls if agent == 'C']
    assert requests[0].questions != requests[1].questions
    assert state['error_count'] == 0


def test_quality_failure_rewrites_report_without_repeating_research():
    agents, calls = researchers(wrong_reference=True)
    state = run(agents)
    assert state['status'] == 'passed'
    assert counts(calls)['F'] == counts(calls)['G'] == 2
    assert counts(calls)['B'] == counts(calls)['C'] == counts(calls)['E'] == 1
    assert state['report_revision'] == 2


def test_transient_error_is_kept_in_state_and_cleared_after_recovery():
    agents, calls = researchers(timeout=True)
    state = run(agents)
    assert state['status'] == 'passed'
    assert state['error_count'] == 1 and state['task_errors'] == {}
    assert state['last_error'].retryable and state['last_error'].ts.tzinfo is not None
    assert state['retry_counts'][state['run_id'] + ':C'] == 1
    assert counts(calls)['B'] == 1 and counts(calls)['C'] == 2
    assert 'sk-secret' not in str(supervisor_storage_payload(state))


def test_no_progress_and_no_judge_are_not_quality_success():
    agents, calls = researchers(overrides={'C': lambda task, state: ResearchResult()})
    state = run(agents)
    assert state['status'] == 'incomplete'
    assert counts(calls)['C'] == 2  # second identical result stops futile searches
    agents, calls = researchers(no_judge=True)
    state = run(agents)
    assert state['status'] == 'incomplete'
    assert all(item.verdict == 'unknown' for item in state['quality_result'].items)


def test_unresolved_identity_skips_research_but_evaluates_limited_report():
    agents, calls = researchers(unresolved=True)
    state = run(agents)
    assert not any(counts(calls)[a] for a in 'BCD')
    assert counts(calls)['G'] >= 1 and state['status'] == 'incomplete'


def test_invalid_supervisor_route_is_rejected_and_error_budget_terminates():
    def invalid(state):
        return SupervisorDecision(action='write', targets=['F'], reason='premature',
                                  based_on_revision=state['analysis_revision'])
    agents, calls = researchers(supervise=invalid)
    state = run(agents, Limits(max_errors=2))
    assert state['status'] == 'failed' and state['error_count'] == 2
    assert calls == []


def test_stale_report_is_an_error_not_a_current_quality_input():
    def stale(task, state):
        return EvaluationReport(summary='stale', perspectives=[], analysis_revision=999)
    agents, calls = researchers(overrides={'F': stale})
    state = run(agents)
    assert state['status'] == 'failed'
    assert counts(calls)['G'] == 0
    assert state['last_error'].node == 'F'


def test_sqlite_resume_preserves_completed_classification(tmp_path):
    agents, calls = researchers()
    initial = initial_state('로봇 평가', '2026-09-30')
    config = {'configurable': {'thread_id': initial['thread_id']}, 'recursion_limit': 150}
    path = str(tmp_path / 'checkpoint.sqlite3')
    with SqliteSaver.from_conn_string(path) as saver:
        partial = build_supervisor_graph(agents, checkpointer=saver, interrupt_after=['collect']).invoke(initial, config)
        assert partial['company_profile'].company_id == 'robot'
        assert counts(calls) == Counter(A=1)
    # Open a new connection and graph, as a restarted process would.
    with SqliteSaver.from_conn_string(path) as saver:
        result = build_supervisor_graph(agents, checkpointer=saver).invoke(None, config)
    assert result['status'] == 'passed'
    assert counts(calls)['A'] == 1
    assert result['run_id'] == initial['run_id']


def test_missing_or_future_evidence_is_rejected_before_synthesis():
    def bad(task, state):
        return ResearchResult(perspectives=[PerspectiveResult(view='technology', findings=[
            CitedClaim(text='지원되지 않은 사실', evidence_ids=['nonexistent'])])])
    agents, calls = researchers(overrides={'B': bad})
    state = run(agents)
    assert state['status'] != 'passed'
    assert any(e.node == 'B' for e in state['task_errors'].values())


def test_step_budget_is_enforced_even_with_custom_policy():
    agents, calls = researchers()
    state = run(agents, Limits(max_steps=4))
    assert state['status'] == 'failed' and state['step_count'] <= 4


def test_failed_sufficiency_gate_cannot_be_overridden_by_passing_report_judge():
    from skala_rag.agents.supervisor import SupervisorPolicy
    def policy(state):
        decision = SupervisorPolicy()(state)
        if decision.action == 'synthesize':
            return decision.model_copy(update={'sufficient': False, 'reason': '확인할 적용 조건 부족'})
        return decision
    agents, _ = researchers(supervise=policy)
    state = run(agents)
    assert state['quality_result'].passed
    assert state['research_sufficient'] is False and state['status'] == 'incomplete'
