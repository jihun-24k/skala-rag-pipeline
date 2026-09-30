"""LangGraph assembly for the six-agent investment workflow."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from skala_rag.agents import InvestmentAgents
from skala_rag.graph.state import InvestmentInput, InvestmentOutput, InvestmentState
from skala_rag.models import (
    CompetitorAnalysis, FinancialAssessment, InvestmentDecision, InvestmentReport,
    MarketAssessment, MissingFact, TechAssessment,
)


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
        classifier = agents.classify_market
        if hasattr(classifier, "classify_state"):
            result = classifier.classify_state(state)
        else:
            result = classifier(state.get("query", ""), state["as_of_date"])
        update: dict[str, object] = {
            "company_profile": result.company_profile,
            "market_category": result.market_category,
        }
        if result.current_company is not None:
            update["current_company"] = result.current_company
        return update

    def analyze_technology(state: InvestmentState) -> dict[str, object]:
        result = agents.analyze_technology(
            state["company_profile"], state["market_category"], state.get("query", "")
        )
        return {"tech_analysis": result.assessment, "evidence": result.evidence}

    def route_classification(state: InvestmentState) -> list[str]:
        profile = state["company_profile"]
        category = state["market_category"]
        unresolved = {"", "분류 검토 필요", "미확정", "미확인", "unknown", "unclassified"}
        if (category.review_required or profile.physical_ai_type.strip().casefold() in unresolved
                or category.sub_industry.strip().casefold() in unresolved):
            return ["classification_review"]
        return ["analyze_technology", "analyze_market"]

    def classification_review(state: InvestmentState) -> dict[str, object]:
        """Stop unclassified companies before assessment agents incur cost."""
        profile = state["company_profile"]
        reason = str(state.get("current_company", {}).get("classification_reason") or
                     "기업 형태 또는 동일 기업 여부에 대한 확인 필요")
        missing = MissingFact(field="physical_ai_type", reason=reason,
                              sources_checked=profile.source_urls)
        return {
            "tech_analysis": TechAssessment(product_summary="분류 검토로 분석 미수행", missing_facts=[missing]),
            "market_analysis": MarketAssessment(missing_facts=[missing]),
            "competitor_analysis": CompetitorAnalysis(missing_facts=[missing]),
            "financial_analysis": FinancialAssessment(missing_facts=[missing]),
            "scores": {},
            "decision": InvestmentDecision(
                decision="추가 실사", total_score=None, confidence=0,
                conditions=[reason],
            ),
            "report": InvestmentReport(
                summary=f"{profile.company_name}: 분류 확인을 위한 추가 실사",
                technology="분류 검토로 분석 미수행",
                market_competition="분류 검토로 분석 미수행",
                financials="분류 검토로 분석 미수행",
                risks=reason,
                decision="추가 실사 — 평가점수 미산정",
                references=profile.source_urls,
            ),
        }

    def analyze_market(state: InvestmentState) -> dict[str, object]:
        result = agents.analyze_market(
            state["company_profile"], state["market_category"], state.get("query", "")
        )
        return {
            "market_analysis": result.assessment,
            "competitor_analysis": getattr(result, "competitor_analysis", CompetitorAnalysis()),
            "evidence": result.evidence,
        }

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
    builder.add_node("classification_review", classification_review)
    builder.add_node("analyze_technology", analyze_technology)
    builder.add_node("analyze_market", analyze_market)
    builder.add_node("analyze_financials", analyze_financials)
    builder.add_node("make_decision", make_decision)
    builder.add_node("write_report", write_report)

    builder.add_edge(START, "classify_market")
    builder.add_conditional_edges(
        "classify_market", route_classification,
        ["analyze_technology", "analyze_market", "classification_review"],
    )
    builder.add_edge("classification_review", END)
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
