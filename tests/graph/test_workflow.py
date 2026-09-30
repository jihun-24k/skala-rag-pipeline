from datetime import date

from skala_rag.agents import (
    AnalysisResult,
    ClassificationResult,
    DecisionResult,
    InvestmentAgents,
)
from skala_rag.graph import build_investment_graph
from skala_rag.models import (
    CompanyProfile,
    Evidence,
    FinancialAssessment,
    InvestmentDecision,
    InvestmentReport,
    MarketAssessment,
    MarketCategory,
    ScoreDetail,
    TechAssessment,
)


def evidence(evidence_id: str) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        claim_text=f"claim-{evidence_id}",
        stance="support",
        source_type="first_party",
        source_grade="C",
        source_uri=f"https://example.com/{evidence_id}",
        confidence=0.8,
    )


def test_graph_runs_parallel_analyses_then_fans_in() -> None:
    calls: list[str] = []
    shared = evidence("EVD-SHARED")

    def classify(query: str, as_of_date: str) -> ClassificationResult:
        calls.append("classify")
        return ClassificationResult(
            company_profile=CompanyProfile(
                company_id="robot-1",
                company_name="Robot One",
                physical_ai_type="industrial_robot",
                stage="Series A",
                as_of_date=date.fromisoformat(as_of_date),
            ),
            market_category=MarketCategory(
                industry="Robotics",
                sub_industry="Industrial automation",
                target_market=["manufacturing"],
                customer_type=["B2B"],
                analysis_scope=[query],
            ),
        )

    def technology(profile, category, query):
        calls.append("technology")
        return AnalysisResult(
            TechAssessment(
                product_summary="robot",
                core_technology=["vision"],
                evidence_ids=["EVD-TECH", shared.evidence_id],
            ),
            [evidence("EVD-TECH"), shared],
        )

    def market(profile, category, query):
        calls.append("market")
        return AnalysisResult(
            MarketAssessment(
                tam="KRW 1T",
                customer_segments=["factory"],
                evidence_ids=["EVD-MARKET", shared.evidence_id],
            ),
            [evidence("EVD-MARKET"), shared],
        )

    def finance(profile, tech, market_result):
        calls.append("finance")
        assert "technology" in calls and "market" in calls
        return AnalysisResult(
            FinancialAssessment(
                revenue="KRW 1B",
                evidence_ids=["EVD-FINANCE"],
            ),
            [evidence("EVD-FINANCE")],
        )

    def decide(tech, market_result, financial, all_evidence):
        calls.append("decision")
        assert {item.evidence_id for item in all_evidence} == {
            "EVD-TECH",
            "EVD-MARKET",
            "EVD-SHARED",
            "EVD-FINANCE",
        }
        score = ScoreDetail(
            dimension="technology",
            score=80,
            weight=1,
            confidence=0.8,
            rationale="supported",
        )
        return DecisionResult(
            decision=InvestmentDecision(
                decision="투자",
                total_score=80,
                confidence=0.8,
                investment_reasons=["strong technology"],
                evidence_ids=["EVD-TECH"],
            ),
            scores={"technology": score},
        )

    def report(profile, tech, market_result, financial, decision, all_evidence, *, scores, market_category):
        calls.append("report")
        assert set(scores) == {"technology"}
        assert market_category.industry == "Robotics"
        return InvestmentReport(
            summary="summary",
            technology="technology",
            market_competition="market",
            financials="financials",
            risks="risks",
            decision=decision.decision,
            references=[item.evidence_id for item in all_evidence],
        )

    graph = build_investment_graph(
        InvestmentAgents(classify, technology, market, finance, decide, report)
    )
    result = graph.invoke(
        {"query": "Robot One을 분석해줘", "as_of_date": "2026-09-30"}
    )

    assert result["report"].decision == "투자"
    assert len(result["evidence"]) == 4
    assert calls[0] == "classify"
    assert calls[-3:] == ["finance", "decision", "report"]


def test_graph_has_expected_six_agent_nodes() -> None:
    noop = lambda *args: None
    graph = build_investment_graph(
        InvestmentAgents(noop, noop, noop, noop, noop, noop)
    )

    assert set(graph.get_graph().nodes) == {
        "__start__",
        "classify_market",
        "classification_review",
        "analyze_technology",
        "analyze_market",
        "analyze_financials",
        "make_decision",
        "write_report",
        "__end__",
    }
