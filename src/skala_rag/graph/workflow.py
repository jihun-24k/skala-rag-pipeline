"""LangGraph assembly for the six-agent investment workflow."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from skala_rag.agents import InvestmentAgents
from skala_rag.graph.state import InvestmentInput, InvestmentOutput, InvestmentState


def build_investment_graph(
    agents: InvestmentAgents,
    *,
    checkpointer: Any | None = None,
):
    """Compile the investment graph with injected agent implementations.

    Technology and market analysis fan out in the same super-step. Financial
    analysis starts only after both are complete, then decision and reporting
    run sequentially.
    """

    def classify_market(state: InvestmentState) -> dict[str, object]:
        result = agents.classify_market(state["query"], state["as_of_date"])
        return {
            "company_profile": result.company_profile,
            "market_category": result.market_category,
        }

    def analyze_technology(state: InvestmentState) -> dict[str, object]:
        result = agents.analyze_technology(
            state["company_profile"], state["market_category"], state["query"]
        )
        return {"tech_analysis": result.assessment, "evidence": result.evidence}

    def analyze_market(state: InvestmentState) -> dict[str, object]:
        result = agents.analyze_market(
            state["company_profile"], state["market_category"], state["query"]
        )
        return {"market_analysis": result.assessment, "evidence": result.evidence}

    def analyze_financials(state: InvestmentState) -> dict[str, object]:
        result = agents.analyze_financials(
            state["company_profile"],
            state["tech_analysis"],
            state["market_analysis"],
        )
        return {
            "financial_analysis": result.assessment,
            "evidence": result.evidence,
        }

    def make_decision(state: InvestmentState) -> dict[str, object]:
        result = agents.make_decision(
            state["tech_analysis"],
            state["market_analysis"],
            state["financial_analysis"],
            state.get("evidence", []),
        )
        return {"decision": result.decision, "scores": result.scores}

    def write_report(state: InvestmentState) -> dict[str, object]:
        report = agents.write_report(
            state["company_profile"],
            state["tech_analysis"],
            state["market_analysis"],
            state["financial_analysis"],
            state["decision"],
            state.get("evidence", []),
            scores=state.get("scores"),
            market_category=state.get("market_category"),
        )
        return {"report": report}

    builder = StateGraph(
        InvestmentState,
        input_schema=InvestmentInput,
        output_schema=InvestmentOutput,
    )
    builder.add_node("classify_market", classify_market)
    builder.add_node("analyze_technology", analyze_technology)
    builder.add_node("analyze_market", analyze_market)
    builder.add_node("analyze_financials", analyze_financials)
    builder.add_node("make_decision", make_decision)
    builder.add_node("write_report", write_report)

    builder.add_edge(START, "classify_market")
    builder.add_edge("classify_market", "analyze_technology")
    builder.add_edge("classify_market", "analyze_market")
    builder.add_edge(
        ["analyze_technology", "analyze_market"], "analyze_financials"
    )
    builder.add_edge("analyze_financials", "make_decision")
    builder.add_edge("make_decision", "write_report")
    builder.add_edge("write_report", END)

    return builder.compile(
        checkpointer=checkpointer,
        name="physical-ai-investment-analysis",
    )
