"""Local smoke run; a model is used only when explicitly configured."""
import argparse
import json

from skala_rag.agents.market_classification import MarketClassificationAgent
from .agent import MarketCompetitionAgent
from .generation import LangChainMarketGenerator


def main():
    parser = argparse.ArgumentParser(description='C 시장·경쟁 분석: 기본은 검색만 실행')
    parser.add_argument('--company-id', required=True)
    parser.add_argument('--as-of-date', required=True)
    parser.add_argument('--model', help='Optional LangChain provider:model identifier; provider package/key required')
    args = parser.parse_args()
    classified = MarketClassificationAgent().classify_company({'company_id': args.company_id}, as_of_date=args.as_of_date)
    generator = None
    if args.model:
        from langchain.chat_models import init_chat_model
        generator = LangChainMarketGenerator(init_chat_model(args.model, temperature=0))
    result = MarketCompetitionAgent(generator=generator)(classified.company_profile, classified.market_category)
    print(json.dumps({
        'market_analysis': result.market_analysis.model_dump(mode='json'),
        'competitor_analysis': result.competitor_analysis.model_dump(mode='json'),
        'evidence': [item.model_dump(mode='json') for item in result.evidence],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
