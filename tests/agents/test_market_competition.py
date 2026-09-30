import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from skala_rag.agents.market_competition import (
    MarketCompetitionAgent, MarketDocument, LocalMarketRetriever, MarketDraft, load_documents,
)
from skala_rag.models import CompanyProfile, MarketCategory


def doc(identity, scope='company', **updates):
    data = dict(document_id=identity, title='배송 로봇 시장 고객 도입',
                text='새빛로봇 배송 로봇의 고객은 사업장 운영사. 고객사 발표에 따르면 사업장에 도입.',
                source_url='https://example.com/'+identity, source_grade='B', scope=scope,
                company_ids=['new-company'] if scope == 'company' else [],
                forms=['mobile_robot'] if scope == 'industry' else [], observed_at='2026-09-01')
    data.update(updates)
    return MarketDocument(**data)


def profile(identity='new-company'):
    return CompanyProfile(company_id=identity, company_name='새빛로봇', physical_ai_type='이동형 로봇',
                          stage='미확인', as_of_date=date(2026, 9, 30))


class MarketCompetitionTests(unittest.TestCase):
    def test_retriever_scopes_dates_future_and_dedup(self):
        docs = [doc('own'), doc('other', company_ids=['other']),
                doc('future-date', published_at='2027-01-01'),
                doc('future-observed', observed_at='2027-01-01'),
                doc('plan', future_plan=True), doc('E', source_grade='E'),
                doc('industry', 'industry'), doc('unrelated', 'industry', forms=['drone'])]
        retriever = LocalMarketRetriever(docs)
        params = dict(company_ids={'new-company'}, forms={'mobile_robot'}, as_of_date=date(2026, 9, 30))
        self.assertEqual([c.document.document_id for c in retriever.search('배송 로봇', scope='company', **params)], ['own'])
        self.assertEqual([c.document.document_id for c in retriever.search('배송 로봇', scope='industry', **params)], ['industry'])
        with self.assertRaises(ValueError):
            LocalMarketRetriever([doc('dup'), doc('dup')])

    def test_no_model_returns_only_retrieval_and_missing_facts(self):
        agent = MarketCompetitionAgent(LocalMarketRetriever([doc('one')]))
        result = agent.analyze(profile())
        self.assertEqual(result.market_analysis.analysis_status, 'retrieval_only')
        self.assertFalse(result.market_analysis.findings)
        self.assertIsNone(result.market_analysis.tam)
        self.assertEqual(result.evidence[0].source_uri, 'https://example.com/one')
        self.assertIn('generation', [f.field for f in result.market_analysis.missing_facts])
        self.assertIn('industry_evidence', [f.field for f in result.market_analysis.missing_facts])

    def test_generation_both_lanes_and_separate_competitor_output(self):
        class Generator:
            def generate(self, payload):
                self.payload = payload
                ctx = payload['retrieved_context']
                own = next(x for x in ctx if x['scope'] == 'company')
                common = next(x for x in ctx if x['scope'] == 'industry')
                return MarketDraft.model_validate({'claims': [
                    {'topic': 'definition', 'text': '사업장 배송 자동화 시장',
                     'citations': [{'chunk_id': common['chunk_id'], 'quote': common['text']}]},
                    {'topic': 'competition', 'text': '예시 경쟁사와 사업장 배송 고객군 중첩; 독립 검증 필요',
                     'competitor_name': '예시 경쟁사',
                     'citations': [{'chunk_id': own['chunk_id'], 'quote': own['text']}]},
                ]})
        generator = Generator()
        result = MarketCompetitionAgent(LocalMarketRetriever([
            doc('own', text='새빛로봇과 예시 경쟁사는 사업장 배송 고객군이 중첩된다는 고객사 발표.'),
            doc('common', 'industry'),
        ]), generator).analyze(profile())
        self.assertEqual(result.market_analysis.analysis_status, 'draft_requires_review')
        self.assertEqual(len(result.competitor_analysis.comparisons), 1)
        self.assertEqual(result.market_analysis.competitors, ['예시 경쟁사'])
        known = {e.evidence_id for e in result.evidence}
        self.assertTrue(all(set(f.evidence_ids) <= known for f in result.market_analysis.findings))
        self.assertNotIn('score', result.market_analysis.model_dump())
        self.assertIsNone(result.market_analysis.tam)
        self.assertIn('tam', [f.field for f in result.market_analysis.missing_facts])

    def test_invented_citation_and_quote_are_rejected(self):
        generator = Mock()
        generator.generate.return_value = {'claims': [
            {'topic': 'tam', 'text': '시장 999조', 'citations': [{'chunk_id': 'fake', 'quote': '존재하지 않는 인용문'}]},
            {'topic': 'traction', 'text': '매출 입증', 'citations': [{'chunk_id': 'one#char=0', 'quote': '존재하지 않는 인용문'}]},
        ]}
        result = MarketCompetitionAgent(LocalMarketRetriever([doc('one')]), generator).analyze(profile())
        self.assertFalse(result.market_analysis.findings)
        self.assertFalse(result.evidence)
        self.assertIsNone(result.market_analysis.tam)
        self.assertEqual(result.market_analysis.analysis_status, 'insufficient_evidence')

    def test_missing_data_and_classification_review_do_not_call_generator(self):
        gen = Mock()
        agent = MarketCompetitionAgent(LocalMarketRetriever([]), gen)
        result = agent.analyze(profile())
        self.assertEqual(result.market_analysis.analysis_status, 'insufficient_evidence')
        category = MarketCategory(industry='Physical AI', sub_industry='이동형 로봇', review_required=True)
        self.assertEqual(agent(profile(), category).assessment.analysis_status, 'classification_review')
        gen.generate.assert_not_called()

    def test_shared_industry_document_reused_for_unregistered_companies(self):
        agent = MarketCompetitionAgent(LocalMarketRetriever([doc('shared', 'industry')]))
        first = agent.analyze(profile('random-a'))
        second = agent.analyze(profile('random-b'))
        self.assertEqual(first.evidence[0].evidence_id, second.evidence[0].evidence_id)

    def test_explicit_competitor_ids_only(self):
        gen = Mock()
        gen.generate.return_value = {'claims': []}
        agent = MarketCompetitionAgent(LocalMarketRetriever([doc('own'), doc('rival', company_ids=['rival'])]), gen)
        agent.analyze(profile())
        self.assertEqual(len(gen.generate.call_args.args[0]['retrieved_context']), 1)
        agent.analyze(profile(), competitor_ids=['rival'])
        self.assertEqual(len(gen.generate.call_args.args[0]['retrieved_context']), 2)

    def test_markdown_loader_and_shared_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'data').mkdir()
            (root/'source.md').write_text('---\ndoc_id: x\n---\n\n# 고객 도입\n실제 MD 본문', encoding='utf-8')
            manifest = {'as_of_date': '2026-09-30', 'sources': [{
                'id': 'one', 'company_id': 'new-company', 'title': '시장 자료',
                'uri': 'https://example.com/one', 'source_grade': 'B',
                'canonical_paths': {'new-company': 'source.md'},
            }]}
            (root/'data/source_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            (root/'data/market_documents.jsonl').write_text(doc('common', 'industry').model_dump_json()+'\n', encoding='utf-8')
            docs = load_documents(root)
            self.assertEqual(len(docs), 2)
            self.assertIn('실제 MD 본문', docs[0].text)
            self.assertNotIn('doc_id:', docs[0].text)
            self.assertEqual(docs[1].scope, 'industry')

    def test_real_inventory_loads_and_retains_original_links(self):
        docs = load_documents()
        self.assertGreater(len(docs), 0)
        result = MarketCompetitionAgent(LocalMarketRetriever(docs)).analyze(profile('neubility'))
        self.assertTrue(result.evidence)
        self.assertTrue(all(e.source_uri.startswith('http') for e in result.evidence))


if __name__ == '__main__':
    unittest.main()
