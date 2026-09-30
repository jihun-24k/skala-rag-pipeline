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
