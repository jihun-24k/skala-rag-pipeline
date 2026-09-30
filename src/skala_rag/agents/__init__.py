"""Agent interfaces consumed by the LangGraph workflow."""

from skala_rag.agents.interfaces import (
    AnalysisResult,
    ClassificationResult,
    DecisionResult,
    InvestmentAgents,
)
from skala_rag.agents.market_classification import MarketClassificationAgent
from skala_rag.agents.market_competition import MarketCompetitionAgent

__all__ = [
    "AnalysisResult",
    "ClassificationResult",
    "DecisionResult",
    "InvestmentAgents",
    "MarketClassificationAgent",
    "MarketCompetitionAgent",
]
