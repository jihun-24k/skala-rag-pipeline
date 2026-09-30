import unittest
from unittest.mock import patch

from skala_rag.agents.market_classification import MarketClassificationAgent, DiscoveryHit
from skala_rag.agents.market_classification.discovery import classify_discovered, forms_from_text
from skala_rag.agents.market_classification.identity import normalized_name, mentions_name


class ClassificationEdgeTests(unittest.TestCase):
    def test_all_ten_forms_with_spacing_and_short_terms(self):
        cases = {
            '협동 로봇': 'fixed_manipulator',
            '로봇팔': 'fixed_manipulator',
            '배송로봇': 'mobile_robot',
            '모바일 매니퓰레이터': 'mobile_manipulator',
            '휴머노이드': 'humanoid',
            '4 족 보행 로봇': 'legged_robot',
            '무인기': 'drone',
            '수중로봇': 'marine_robot',
            '웨어러블로봇': 'wearable_exoskeleton',
            '자율 주행차': 'autonomous_vehicle',
            'AI카메라': 'smart_space',
        }
        for phrase, key in cases.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(forms_from_text(phrase), {key})

    def test_same_document_multiple_forms_are_preserved(self):
        decision = classify_discovered('새빛로봇', [DiscoveryHit(
            '새빛로봇 제품', '새빛로봇의 휴머노이드와 협동 로봇, 외골격 제품군',
            'https://example.com/products', 'C',
        )])
        self.assertIsNone(decision.form_key)
        self.assertEqual(decision.status, 'conflicting_forms')
        self.assertEqual(set(decision.candidate_forms), {'humanoid', 'fixed_manipulator', 'wearable_exoskeleton'})

    def test_corporate_names_and_word_boundaries(self):
        self.assertEqual(normalized_name('(주) 새빛 로봇'), normalized_name('주식회사 새빛로봇'))
        self.assertEqual(normalized_name('㈜새빛로봇'), normalized_name('새빛로봇'))
        self.assertTrue(mentions_name('주식회사 새빛 로봇은 제품을 공개', '새빛로봇'))
        self.assertTrue(mentions_name('Example Robotics Inc. builds robots', 'ExampleRobotics'))
        self.assertFalse(mentions_name('SuperExampleRoboticsX', 'Example Robotics'))
        self.assertFalse(mentions_name('새빛로봇틱스 제품', '새빛로봇'))
        self.assertEqual(forms_from_text('farm management software'), set())

    def test_provided_english_alias_and_secondary_forms_in_state(self):
        result = MarketClassificationAgent().classify_state({
            'as_of_date': '2026-09-30', 'current_index': 0,
            'candidate_companies': [{
                'name': '(주)새빛로봇', 'aliases': ['Saebit Robotics Inc.'],
                'evidence': [{
                    'title': 'Saebit Robotics',
                    'text': 'Saebit Robotics develops humanoid and quadruped platforms.',
                    'url': 'https://example.com/products', 'official': True,
                }],
            }],
        })
        self.assertEqual(result.company_profile.classification_status, 'conflicting_forms')
        self.assertEqual(set(result.market_category.secondary_forms), {'휴머노이드', '다족보행 로봇'})
        self.assertTrue(result.market_category.review_required)

    def test_registered_names_normalize_in_both_input_formats(self):
        agent = MarketClassificationAgent()
        self.assertEqual(agent('주식회사 위로보틱스를 분류해줘', '2026-09-30').company_profile.company_id, 'wirobotics')
        for candidate in ['WI Robotics Inc.', {'name': '(주) 위 로보틱스'}]:
            with self.subTest(candidate=candidate):
                result = agent.classify_state({'as_of_date': '2026-09-30', 'candidate_companies': [candidate], 'current_index': 0})
                self.assertEqual(result.company_profile.company_id, 'wirobotics')

    def test_name_only_without_search_key_remains_unresolved(self):
        with patch.dict('os.environ', {'BRAVE_SEARCH_API_KEY': ''}):
            result = MarketClassificationAgent()('새빛로봇', '2026-09-30')
        self.assertEqual(result.company_profile.classification_status, 'insufficient_evidence')
        self.assertFalse(result.company_profile.source_urls)

    def test_structured_company_needs_no_query(self):
        result = MarketClassificationAgent().classify_company({
            'company_name': '새빛로봇',
            'evidence': [{'text': '새빛로봇은 배송로봇을 개발',
                          'url': 'https://example.com/robot', 'official': True}],
        }, as_of_date='2026-09-30')
        self.assertEqual(result.company_profile.physical_ai_type, '이동형 로봇')
        self.assertEqual(result.company_profile.source_urls, ['https://example.com/robot'])

    def test_new_evidence_overrides_registered_form_without_mutating_master(self):
        agent = MarketClassificationAgent()
        # Synthetic fixture, not a claim about this company's real products.
        result = agent.classify_company({
            'company_id': 'neubility',
            'evidence': [{'text': 'Neubility develops underwater robots.',
                          'url': 'https://example.com/new-product', 'official': True}],
        }, as_of_date='2026-09-30')
        self.assertEqual(result.company_profile.company_id, 'neubility')
        self.assertEqual(result.company_profile.physical_ai_type, '해양·수중 로봇')
        self.assertTrue(result.market_category.review_required)
        self.assertEqual(result.current_company['primary_form'], 'marine_robot')
        old = agent.classify_company({'company_id': 'neubility'}, as_of_date='2026-09-30')
        self.assertEqual(old.current_company['primary_form'], 'mobile_robot')

    def test_explicit_empty_evidence_never_falls_back_to_master_or_search(self):
        from unittest.mock import Mock
        search = Mock()
        agent = MarketClassificationAgent(discovery=search)
        for name in ['neubility', '새빛로봇']:
            result = agent.classify_company({'name': name, 'evidence': []}, as_of_date='2026-09-30')
            self.assertEqual(result.company_profile.classification_status, 'insufficient_evidence')
        search.search.assert_not_called()


if __name__ == '__main__':
    unittest.main()
