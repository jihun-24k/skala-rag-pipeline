import importlib.util
import unittest
from datetime import date
from unittest.mock import Mock

from skala_rag.agents.market_competition import MarketCompetitionAgent, LocalMarketRetriever, MarketDocument
from skala_rag.agents.market_competition.documents import publication_bound
from skala_rag.models import CompanyProfile


class MarketGenerationTests(unittest.TestCase):
    def test_partial_publication_dates_use_conservative_bound(self):
        self.assertEqual(publication_bound('2026'), date(2026, 12, 31))
        self.assertEqual(publication_bound('2024-02'), date(2024, 2, 29))
        self.assertIsNone(publication_bound(None))

    def test_size_requires_metadata_and_numbers_in_quote(self):
        source = MarketDocument(document_id='market', title='배송 로봇 시장 규모',
            text='2025년 한국 사업장 배송 로봇 시장은 100 억원. 공급사 매출 합산 기준.',
            source_url='https://example.com/report', source_grade='A', scope='industry',
            forms=['mobile_robot'], observed_at='2026-09-01')
        profile = CompanyProfile(company_id='new', company_name='새빛로봇', physical_ai_type='이동형 로봇',
                                 stage='미확인', as_of_date=date(2026, 9, 30))
        generator = Mock()
        claim = {'topic': 'tam', 'text': '시장 규모', 'citations': [{'chunk_id': 'market#char=0', 'quote': source.text}]}
        generator.generate.return_value = {'claims': [claim]}
        agent = MarketCompetitionAgent(LocalMarketRetriever([source]), generator)
        self.assertIsNone(agent.analyze(profile).market_analysis.tam)
        claim['market_size'] = dict(value='999', unit='억원', base_year=2025, geography='한국',
                                    segment='사업장 배송 로봇', methodology='공급사 매출 합산')
        self.assertIsNone(agent.analyze(profile).market_analysis.tam)
        claim['market_size']['value'] = '100'
        self.assertIn('100 억원', agent.analyze(profile).market_analysis.tam)

    @unittest.skipUnless(importlib.util.find_spec('langchain'), 'optional langchain dependency')
    def test_langchain_adapter_with_offline_tool_call_model(self):
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        from skala_rag.agents.market_competition import LangChainMarketGenerator
        class OfflineModel(BaseChatModel):
            @property
            def _llm_type(self):
                return 'offline-test'
            def bind_tools(self, tools, **kwargs):
                return self
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[{
                    'name': 'MarketDraft', 'args': {'claims': [], 'limitations': ['시장규모 자료 부족']},
                    'id': 'test-call', 'type': 'tool_call',
                }]))])
        draft = LangChainMarketGenerator(OfflineModel()).generate({'retrieved_context': []})
        self.assertEqual(draft.limitations, ['시장규모 자료 부족'])


if __name__ == '__main__':
    unittest.main()
