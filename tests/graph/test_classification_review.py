import unittest
from datetime import date
from unittest.mock import Mock

from skala_rag.agents import InvestmentAgents, ClassificationResult, MarketClassificationAgent
from skala_rag.graph import build_investment_graph
from skala_rag.models import CompanyProfile, MarketCategory


class ClassificationReviewTests(unittest.TestCase):
    def run_guarded_graph(self, classifier, state):
        downstream = [Mock(side_effect=AssertionError('downstream agent must not run')) for _ in range(5)]
        graph = build_investment_graph(InvestmentAgents(classifier, *downstream))
        result = graph.invoke(state)
        for mock in downstream:
            mock.assert_not_called()
        self.assertEqual(result['decision'].decision, '추가 실사')
        self.assertIsNone(result['decision'].total_score)
        self.assertEqual(result['scores'], {})
        self.assertEqual(result['report'].decision, '추가 실사 — 평가점수 미산정')
        return result

    def test_new_company_proposal_skips_analysis(self):
        result = self.run_guarded_graph(MarketClassificationAgent(), {
            'as_of_date': '2026-09-30', 'current_index': 0,
            'candidate_companies': [{'name': '새빛로봇', 'evidence': [{
                'title': '새빛로봇', 'text': '새빛로봇은 4족 보행 로봇을 개발',
                'url': 'https://example.com/robot', 'official': True,
            }]}],
        })
        self.assertEqual(result['company_profile'].physical_ai_type, '다족보행 로봇')
        self.assertEqual(result['report'].references, ['https://example.com/robot'])

    def test_unclassified_form_skips_even_when_flag_is_false(self):
        classifier = lambda *args: ClassificationResult(
            CompanyProfile(company_id='new', company_name='신규기업', physical_ai_type='미확정',
                           stage='미확인', as_of_date=date(2026, 9, 30)),
            MarketCategory(industry='Physical AI', sub_industry='미확정', review_required=False),
        )
        self.run_guarded_graph(classifier, {'query': '신규기업', 'as_of_date': '2026-09-30'})


if __name__ == '__main__':
    unittest.main()
