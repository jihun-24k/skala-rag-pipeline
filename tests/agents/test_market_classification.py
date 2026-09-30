"""Regression checks against the ten-company research snapshot."""

import unittest
from datetime import date

from skala_rag.agents.market_classification import (
    CompanyNotFoundError,
    DiscoveryHit,
    FORMS,
    MarketClassificationAgent,
)


class MarketClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = MarketClassificationAgent()

    def test_all_registered_companies_and_unknown_forms(self):
        companies = self.agent.catalog.list_companies()
        self.assertEqual(len(companies), 10)
        for index, company in enumerate(companies):
            with self.subTest(company=company["id"]):
                result = self.agent.classify_state({
                    "query": "10개사 순차 평가",
                    "as_of_date": "2026-09-30",
                    "candidate_companies": [item["id"] for item in companies],
                    "current_index": index,
                })
                self.assertEqual(result.current_company["company_id"], company["id"])
                self.assertEqual(result.company_profile.as_of_date, date(2026, 9, 30))
                self.assertTrue(result.company_profile.source_urls)
                if company["classification"]["primary_form"] is None:
                    self.assertTrue(result.market_category.review_required)
                    self.assertEqual(result.company_profile.physical_ai_type, "분류 검토 필요")
                    self.assertFalse(result.market_category.priority_metrics)
                else:
                    self.assertIn(result.company_profile.physical_ai_type, {
                        form.label for form in FORMS.values()
                    })

    def test_queue_index_wins_over_query_name(self):
        result = self.agent.classify_state({
            "query": "로브로스와 위로보틱스 비교",
            "as_of_date": "2026-09-30",
            "candidate_companies": ["robros", "wirobotics"],
            "current_index": 1,
        })
        self.assertEqual(result.company_profile.company_id, "wirobotics")
        self.assertEqual(result.company_profile.physical_ai_type, "웨어러블·외골격")
        self.assertIn("휴머노이드", result.market_category.secondary_forms)

    def test_unknown_names_need_sources_and_ambiguous_registered_names_fail(self):
        for query in ("라온로보틱스", "real world"):
            with self.subTest(query=query):
                result = MarketClassificationAgent(discovery=NoSearch())(query, "2026-09-30")
                self.assertEqual(result.market_category.sub_industry, "분류 검토 필요")
                self.assertEqual(result.company_profile.classification_status, "insufficient_evidence")
        with self.assertRaises(CompanyNotFoundError):
            self.agent("로브로스와 뉴빌리티 비교", "2026-09-30")

    def test_arbitrary_company_from_supplied_official_source(self):
        result = self.agent.classify_state({
            "query": "신규 기업 분류",
            "as_of_date": "2026-09-30",
            "candidate_companies": [{
                "name": "테스트로보틱스",
                "evidence": [{
                    "title": "테스트로보틱스 제품",
                    "text": "테스트로보틱스는 4족 보행 로봇을 개발",
                    "url": "https://example.com/robot",
                    "official": True,
                }],
            }],
            "current_index": 0,
        })
        self.assertEqual(result.company_profile.physical_ai_type, "다족보행 로봇")
        self.assertEqual(result.company_profile.classification_status, "proposed_needs_review")
        self.assertTrue(result.market_category.review_required)
        self.assertEqual(result.company_profile.source_urls, ["https://example.com/robot"])

    def test_arbitrary_name_search_and_conflicting_forms(self):
        found = MarketClassificationAgent(discovery=FakeSearch([
            DiscoveryHit("새빛로봇", "새빛로봇 4족 보행 로봇", "https://one.example/a"),
            DiscoveryHit("새빛로봇", "새빛로봇 4족 보행 로봇", "https://two.example/b"),
        ]))("새빛로봇", "2026-09-30")
        self.assertEqual(found.company_profile.physical_ai_type, "다족보행 로봇")
        conflict = MarketClassificationAgent(discovery=FakeSearch([
            DiscoveryHit("새빛로봇", "새빛로봇 4족 보행 로봇", "https://one.example/a"),
            DiscoveryHit("새빛로봇", "새빛로봇 배송 로봇", "https://two.example/b"),
        ]))("새빛로봇", "2026-09-30")
        self.assertEqual(conflict.company_profile.classification_status, "conflicting_forms")
        self.assertEqual(conflict.company_profile.physical_ai_type, "분류 검토 필요")

    def test_natural_language_name_and_search_failure(self):
        found = MarketClassificationAgent(discovery=FakeSearch([
            DiscoveryHit("새빛로봇", "새빛로봇 4족 보행 로봇", "https://one.example/a"),
            DiscoveryHit("새빛로봇", "새빛로봇 4족 보행 로봇", "https://two.example/b"),
        ]))("새빛로봇을 분석해줘", "2026-09-30")
        self.assertEqual(found.company_profile.company_name, "새빛로봇")
        self.assertEqual(found.company_profile.physical_ai_type, "다족보행 로봇")
        unavailable = MarketClassificationAgent(discovery=FailSearch())("새빛로봇", "2026-09-30")
        self.assertEqual(unavailable.company_profile.classification_status, "discovery_unavailable")

    def test_stale_or_out_of_range_snapshot_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "newer"):
            self.agent("뉴빌리티", "2025-09-30")
        with self.assertRaises(IndexError):
            self.agent.classify_state({
                "query": "", "as_of_date": "2026-09-30",
                "candidate_companies": ["robros"], "current_index": 1,
            })


class NoSearch:
    def search(self, company_name):
        return []


class FakeSearch:
    def __init__(self, hits):
        self.hits = hits

    def search(self, company_name):
        return self.hits


class FailSearch:
    def search(self, company_name):
        raise OSError("network failure")


if __name__ == "__main__":
    unittest.main()
