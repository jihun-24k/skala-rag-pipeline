from datetime import date
from types import SimpleNamespace

import pytest

from skala_rag.agents.financial_agent.adapter import FinancialAnalyzerAdapter, unavailable_financials
from skala_rag.agents.financial_agent.models.schemas import FinancialData, FinancialValue
from skala_rag.agents.financial_agent.service.normalizer import FinancialNormalizer
from skala_rag.agents.market_competition.documents import MarketDocument
from skala_rag.models import CompanyProfile, MarketCategory
from skala_rag.retrieval.adapters import FaissMarketRetriever
from skala_rag.retrieval.models import RetrievalHit
from skala_rag.runtime import TechnologyAnalyzer, TechnicalClaims, make_decider


def profile():
    return CompanyProfile(company_id='robros', company_name='로브로스',
        physical_ai_type='휴머노이드', stage='unknown', as_of_date=date(2026, 9, 30))


def document(**extra):
    data = dict(document_id='original', title='제품', text='제품 가반하중 5kg',
        source_url='https://example.org/product', source_grade='C',
        scope='company', company_ids=['robros'], observed_at=date(2026, 9, 30),
        locator='01_로브로스/product.md')
    return MarketDocument(**(data | extra))


class Search:
    def search(self, request):
        self.request = request
        return [RetrievalHit(vector_id=1, score=.8, chunk_id='chunk', document_id='old-id',
            title='제품', text='제품 가반하중 5kg', source_path='자료조사/01_로브로스/product.md',
            company_id='company-01', source_type='research_note', source_grade='D', dimension='product')]


def test_vector_adapter_joins_identity_and_preserves_original_metadata():
    search = Search()
    adapter = FaissMarketRetriever(search, [document()], fetch_k=1000)
    chunks = adapter.search('제품', scope='company', company_ids={'robros'}, forms=set(),
                            as_of_date=date(2026, 9, 30))
    assert len(chunks) == 1
    assert chunks[0].document.source_grade == 'C'
    assert search.request.source_paths == ['01_로브로스/product.md']
    assert adapter.search('제품', scope='company', company_ids={'other'}, forms=set(),
                          as_of_date=date(2026, 9, 30)) == []
    assert adapter.search('제품', scope='company', company_ids={'robros'}, forms=set(),
                          as_of_date=date(2025, 9, 30)) == []


def test_technology_rejects_invented_quotes():
    class Model:
        def with_structured_output(self, schema):
            return self
        def invoke(self, messages):
            return TechnicalClaims(claims=[dict(chunk_id='chunk', quote='가반하중 500kg',
                stance='support', topic='product_spec')])
    adapter = FaissMarketRetriever(Search(), [document()], fetch_k=100)
    analyzer = TechnologyAnalyzer(adapter, Model())
    with pytest.raises(ValueError, match='non-verbatim'):
        analyzer(profile(), MarketCategory(industry='로봇', sub_industry='휴머노이드'), '기술 분석')


def test_financial_adapter_keeps_provenance_and_rejects_future_values():
    data = FinancialData(revenue=FinancialValue(value=100, unit='KRW', source='dart',
        as_of='2025-12-31', receipt_no='123'), total_assets=FinancialValue(
        value=200, unit='KRW', source='dart', as_of='2025-12-31'),
        total_funding=FinancialValue(value=300, source='fsc', as_of='2027-01-01'))
    agent = SimpleNamespace(normalizer=FinancialNormalizer(),
        collector=SimpleNamespace(collect=lambda _: SimpleNamespace(financials=data, source_reports=[])))
    result = FinancialAnalyzerAdapter(agent)(profile(), None, None)
    assert result.assessment.status == 'available'
    assert result.assessment.total_funding is None
    assert len(result.evidence) == 2
    assert result.assessment.evidence_ids == [e.evidence_id for e in result.evidence]
    assert result.evidence[0].source_uri.endswith('rcpNo=123')


def test_offline_mode_preserves_missing_financials_and_unscored_decision():
    financial = unavailable_financials(profile(), None, None)
    assert financial.assessment.status == 'unavailable'
    result = make_decider(None)(None, None, financial.assessment, [])
    assert result.decision.total_score is None
    assert result.scores == {}


def test_financial_annual_comparatives_keep_scope_unit_and_source():
    data = FinancialData(revenue=FinancialValue(value=100, previous_value=0, unit='KRW', source='dart',
        as_of='2025-12-31', previous_as_of='2024-12-31', receipt_no='123',
        report_type='annual', statement_scope='consolidated'))
    agent = SimpleNamespace(normalizer=FinancialNormalizer(),
        collector=SimpleNamespace(collect=lambda _: SimpleNamespace(financials=data, source_reports=[])))
    result = FinancialAnalyzerAdapter(agent)(profile(), None, None)
    assert len(result.evidence) == 2
    current, previous = result.evidence
    assert previous.value == 0  # actual zero, not a missing value
    assert previous.financial_observation.period_end == date(2024, 12, 31)
    assert current.source_uri == previous.source_uri
    assert current.financial_observation.statement_scope == 'consolidated'
    data.revenue.report_type = 'half_year'
    partial = FinancialAnalyzerAdapter(agent)(profile(), None, None)
    assert len(partial.evidence) == 1 and partial.evidence[0].financial_observation is None


def test_research_schema_limits_role_and_citations(monkeypatch):
    import skala_rag.runtime as runtime
    from skala_rag.agents.interfaces import AnalysisResult
    from skala_rag.models import Evidence, MarketAssessment, TechAssessment
    from skala_rag.models.orchestration import TaskRequest
    from pydantic import ValidationError
    ev = Evidence(evidence_id='known', claim_text='source', stance='support',
                  source_type='official', source_grade='B', source_uri='https://example.test/source')
    legacy = SimpleNamespace(analyze_technology=lambda *args: AnalysisResult(TechAssessment(product_summary='fixture'), [ev]),
        analyze_market=lambda *args: AnalysisResult(MarketAssessment(), [ev]))
    monkeypatch.setattr(runtime, 'build_runtime_agents', lambda **kwargs: legacy)
    checked = []
    class Model:
        def with_structured_output(self, schema):
            def invoke(messages):
                for invalid in [dict(view='stakeholders', findings=[]),
                                dict(view='technology', findings=[dict(text='bad', evidence_ids=['invented'])])]:
                    with pytest.raises(ValidationError):
                        schema.model_validate({'perspectives': [invalid]})
                checked.append(True)
                return {'perspectives': [dict(view='technology', findings=[dict(text='verified', evidence_ids=['known'])])]}
            return SimpleNamespace(invoke=invoke)
    agents = runtime.build_orchestration_agents(model=Model())
    request = TaskRequest(task_id='fixture:B', agent='B', attempt=1, questions=['technology'], reason='fixture', based_on_revision=0)
    payload = agents.workers['B'](request, {'query':'fixture','company_profile':profile(),
        'market_category':MarketCategory(industry='robot',sub_industry='humanoid'),'perspectives':{}})
    assert checked and payload.perspectives[0].findings[0].evidence_ids == ['known']


def test_report_transport_accepts_variable_reference_keys():
    from skala_rag.runtime import _invoke
    from skala_rag.models.orchestration import EvaluationReport
    import json
    seen = []
    class Model:
        def with_structured_output(self, schema, **options):
            # Simulate the provider's strict fixed-key schema restriction.
            if options.get('method') != 'json_schema' or options.get('strict') is not True:
                raise ValueError('provider rejects dynamic dictionaries')
            def invoke(messages):
                payload = json.loads(messages[1][1])
                seen.append(payload)
                for field in ('references', 'classification', 'reference_details'):
                    payload[field] = [{'key':key,'value':value} for key,value in payload.get(field,{}).items()]
                return schema.model_validate(payload)
            return SimpleNamespace(invoke=invoke)
    payload = dict(company_name='fixture', summary='supported', perspectives=[], analysis_revision=1,
                   references={'source:2025:1': 'https://example.test/a'}, classification={'제품 유형': '웨어러블'})
    report = EvaluationReport.model_validate(_invoke(Model(), EvaluationReport, 'fixture', payload))
    assert report.references['source:2025:1'] == 'https://example.test/a'
    assert seen and report.classification['제품 유형'] == '웨어러블'


def test_orchestration_lexical_lane_recovers_product_and_keeps_date_filters():
    class EmptyVector:
        def search(self, request):
            return []
    docs = [document(), document(document_id='future', observed_at=date(2027, 1, 1),
                                locator='future.md', text='제품 가반하중 999kg')]
    adapter = FaissMarketRetriever(EmptyVector(), docs, fetch_k=100, augment_with_lexical=True)
    chunks = adapter.search('제품 가반하중', scope='company', company_ids={'robros'},
                            forms=set(), as_of_date=date(2026, 9, 30), limit=2)
    assert [c.document.document_id for c in chunks] == ['original']
    assert chunks[0].text == '제품 가반하중 5kg'
    assert adapter.search('제품', scope='company', company_ids={'other'}, forms=set(),
                          as_of_date=date(2026, 9, 30)) == []


def test_technical_selection_preserves_source_text_without_model_transcription():
    class Selector:
        def with_structured_output(self, schema):
            self.schema = schema
            return self
        def invoke(self, messages):
            return self.schema.model_validate({'claims': [{'chunk_id': 'chunk',
                'stance': 'support', 'topic': 'product_spec'}]})
    adapter = FaissMarketRetriever(Search(), [document()], fetch_k=100)
    result = TechnologyAnalyzer(adapter, Selector(), retain_research_evidence=True)(
        profile(), MarketCategory(industry='로봇', sub_industry='휴머노이드'), '제품')
    assert len(result.evidence) == 1
    assert result.evidence[0].claim_text == '제품 가반하중 5kg'
    assert result.evidence[0].source_uri == 'https://example.org/product'


def test_initial_supervisor_can_choose_finance_first_from_state(monkeypatch):
    import skala_rag.runtime as runtime
    from skala_rag.graph.supervisor_workflow import initial_state
    from skala_rag.agents.supervisor import validate_decision
    monkeypatch.setattr(runtime, 'build_runtime_agents', lambda **kwargs: SimpleNamespace())
    class Router:
        def with_structured_output(self, schema):
            return SimpleNamespace(invoke=lambda messages: schema.model_validate({
                'targets':['D'], 'reason':'재무 중심 요청의 자료 가용성 우선 확인', 'questions':['연도별 재무자료 확인']}))
    agents = runtime.build_orchestration_agents(model=Router())
    state = initial_state('연도별 재무 중심 평가', '2026-09-30')
    state.update(company_profile=profile(), market_category=MarketCategory(industry='로봇', sub_industry='휴머노이드'))
    route = agents.supervise(state)
    assert route.targets == ['D']
    validate_decision(route, state)
    state['attempts']['D'] = 1
    with pytest.raises(ValueError, match='unavailable initial researcher'):
        agents.supervise(state)


def test_optional_research_stops_at_three_reinvestigations_and_writes_limits(monkeypatch):
    import skala_rag.runtime as runtime
    from skala_rag.graph.supervisor_workflow import initial_state
    from skala_rag.models import Evidence
    from skala_rag.models.orchestration import PerspectiveResult, CitedClaim
    monkeypatch.setattr(runtime, 'build_runtime_agents', lambda **kwargs: SimpleNamespace())
    class Assessor:
        def with_structured_output(self, schema):
            return SimpleNamespace(invoke=lambda messages: schema.model_validate({
                'blocking_issue':'none', 'reason':'고객 정보는 미확인이나 제품 설명 가능',
                'targets':['C'], 'questions':['새로운 고객 자료가 있는지 확인']}))
    agents = runtime.build_orchestration_agents(model=Assessor())
    state = initial_state('평가', '2026-09-30')
    ev = Evidence(evidence_id='known', claim_text='제품 소개', stance='support',
                  source_type='first_party', source_grade='C', source_uri='https://example.test/product')
    state.update(company_profile=profile(),market_category=MarketCategory(industry='로봇',sub_industry='휴머노이드'),
        attempts={'A':1,'B':1,'C':1,'D':1}, evidence=[ev],
        perspectives={'technology':PerspectiveResult(view='technology',findings=[CitedClaim(text='제품 소개',evidence_ids=['known'])])})
    decision = agents.supervise(state)
    assert decision.action == 'research' and decision.targets == ['C'] and decision.sufficient
    state['attempts']['C'] = 4  # Initial + three re-investigations.
    decision = agents.supervise(state)
    assert decision.action == 'synthesize' and decision.sufficient
    assert '한계로 명시' in decision.reason
