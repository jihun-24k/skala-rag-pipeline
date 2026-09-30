import unittest
from datetime import date

from skala_rag.agents import AnalysisResult, ClassificationResult, DecisionResult, InvestmentAgents
from skala_rag.agents.market_competition import MarketCompetitionAgent, LocalMarketRetriever, MarketDocument
from skala_rag.graph import build_investment_graph
from skala_rag.models import (CompanyProfile, MarketCategory, TechAssessment, FinancialAssessment,
                              InvestmentDecision, InvestmentReport)


class MarketIntegrationTests(unittest.TestCase):
    def test_c_outputs_competitor_state_and_passes_findings_to_downstream(self):
        document = MarketDocument(document_id='source', title='배송 경쟁', text='새빛로봇과 경쟁사는 사업장 배송 고객군 중첩.',
                                  source_url='https://example.com/source', source_grade='B', scope='company',
                                  company_ids=['new'], observed_at='2026-09-01')
        class Generator:
            def generate(self, payload):
                c = payload['retrieved_context'][0]
                return {'claims': [{'topic': 'competition', 'text': '사업장 배송 고객군 중첩',
                                    'competitor_name': '경쟁사',
                                    'citations': [{'chunk_id': c['chunk_id'], 'quote': c['text']}]}]}
        c = MarketCompetitionAgent(LocalMarketRetriever([document]), Generator())
        def classify(*args):
            return ClassificationResult(CompanyProfile(company_id='new', company_name='새빛로봇',
                physical_ai_type='이동형 로봇', stage='미확인', as_of_date=date(2026, 9, 30)),
                MarketCategory(industry='Physical AI', sub_industry='이동형 로봇'))
        def report(profile, tech, market, finance, decision, evidence):
            self.assertEqual(market.competitors, ['경쟁사'])
            self.assertEqual(evidence[0].source_uri, document.source_url)
            return InvestmentReport(summary='테스트', technology='', market_competition=market.findings[0].text,
                                    financials='', risks='', decision='추가 실사', references=[e.source_uri for e in evidence])
        graph = build_investment_graph(InvestmentAgents(
            classify, lambda *args: AnalysisResult(TechAssessment(product_summary='테스트')), c,
            lambda *args: AnalysisResult(FinancialAssessment()),
            lambda *args: DecisionResult(InvestmentDecision(decision='추가 실사', confidence=0), {}), report,
        ))
        result = graph.invoke({'candidate_companies': [{'name': '새빛로봇'}], 'as_of_date': '2026-09-30'})
        self.assertEqual(result['competitor_analysis'].comparisons[0].competitor_name, '경쟁사')
        self.assertEqual(result['market_analysis'].analysis_status, 'draft_requires_review')


if __name__ == '__main__':
    unittest.main()
