#!/usr/bin/env python3
"""Run the complete investment-analysis LangGraph without external API keys.

This is a deterministic smoke runner for the six-agent graph. Replace the six
functions in ``build_demo_agents`` with production LLM/RAG implementations when
connecting real services.

Examples:
    python scripts/run_langgraph.py
    python scripts/run_langgraph.py --company "로브로스" --as-of-date 2026-09-30
    python scripts/run_langgraph.py --output storage/runs/demo-result.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from skala_rag.agents import (  # noqa: E402
    AnalysisResult,
    ClassificationResult,
    DecisionResult,
    InvestmentAgents,
)
from skala_rag.graph import build_investment_graph, to_storage_payload  # noqa: E402
from skala_rag.models import (  # noqa: E402
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


def evidence(
    evidence_id: str,
    claim: str,
    *,
    company_id: str,
    source_type: str,
    source_grade: str = "B",
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        claim_text=claim,
        stance="support",
        source_type=source_type,
        source_grade=source_grade,
        source_uri=f"demo://{evidence_id.lower()}",
        locator="demo:1",
        confidence=0.85,
        company_id=company_id,
        independent=source_grade in {"A", "B"},
    )


def build_demo_agents(company_name: str, company_id: str) -> InvestmentAgents:
    """Create deterministic implementations of all six graph contracts."""

    def classify_market(query: str, as_of_date: str) -> ClassificationResult:
        profile = CompanyProfile(
            company_id=company_id,
            company_name=company_name,
            physical_ai_type="휴머노이드",
            stage="Series A",
            as_of_date=date.fromisoformat(as_of_date),
            listing_status="비상장",
            business_model="산업용 휴머노이드 공급",
            classification_status="verified_demo",
        )
        category = MarketCategory(
            industry="Physical AI / Robotics",
            sub_industry="휴머노이드",
            target_market=["제조", "물류"],
            customer_type=["B2B"],
            analysis_scope=[query],
            priority_metrics=["작업 성공률", "가반하중", "연속 운용시간"],
        )
        return ClassificationResult(
            company_profile=profile,
            market_category=category,
            current_company={
                "company_id": company_id,
                "canonical_name": company_name,
                "classification_status": "verified_demo",
            },
        )

    def analyze_technology(
        profile: CompanyProfile,
        category: MarketCategory,
        query: str,
    ) -> AnalysisResult[TechAssessment]:
        item = evidence(
            "DEMO-TECH-001",
            "휴머노이드 플랫폼과 전신 제어 기술을 보유한다.",
            company_id=profile.company_id,
            source_type="academic",
            source_grade="A",
        )
        assessment = TechAssessment(
            product_summary=f"{profile.company_name}의 산업용 휴머노이드 플랫폼",
            core_technology=["전신 제어", "모방학습"],
            strengths=["하드웨어와 제어 소프트웨어의 통합 개발"],
            limitations=["장기 현장 운용 데이터 추가 확인 필요"],
            technical_risks=["대량 생산 단계의 품질 편차"],
            evidence_ids=[item.evidence_id],
        )
        return AnalysisResult(assessment=assessment, evidence=[item])

    def analyze_market(
        profile: CompanyProfile,
        category: MarketCategory,
        query: str,
    ) -> AnalysisResult[MarketAssessment]:
        item = evidence(
            "DEMO-MARKET-001",
            "제조·물류 기업의 반복 작업 자동화 수요가 존재한다.",
            company_id=profile.company_id,
            source_type="market_research",
        )
        assessment = MarketAssessment(
            analysis_status="demo",
            market_definition=["국내 제조·물류용 휴머노이드 시장"],
            customer_segments=["제조사", "물류 운영사"],
            competitors=["글로벌 휴머노이드 OEM"],
            opportunities=["인력 부족 공정의 자동화"],
            market_risks=["도입 비용과 안전 검증 기간"],
            traction=["PoC 이후 반복 구매 여부 확인 필요"],
            evidence_ids=[item.evidence_id],
        )
        return AnalysisResult(assessment=assessment, evidence=[item])

    def analyze_financials(
        profile: CompanyProfile,
        tech: TechAssessment,
        market: MarketAssessment,
    ) -> AnalysisResult[FinancialAssessment]:
        item = evidence(
            "DEMO-FIN-001",
            "예시 재무자료가 확보되어 재무 분석 경로를 실행한다.",
            company_id=profile.company_id,
            source_type="financial_statement",
            source_grade="B",
        )
        assessment = FinancialAssessment(
            status="available",
            revenue="예시 매출 32억원",
            operating_income="예시 영업손실 5억원",
            total_assets="예시 총자산 50억원",
            total_liabilities="예시 총부채 24억원",
            runway_months=18,
            funding_need="양산 설비 및 현장 운영 인력",
            financial_risks=["양산 전 고정비 증가"],
            evidence_ids=[item.evidence_id],
        )
        return AnalysisResult(assessment=assessment, evidence=[item])

    def make_decision(
        tech: TechAssessment,
        market: MarketAssessment,
        financial: FinancialAssessment,
        all_evidence: list[Evidence],
    ) -> DecisionResult:
        evidence_ids = [item.evidence_id for item in all_evidence]
        scores = {
            "technology": ScoreDetail(
                dimension="technology",
                score=80,
                weight=0.4,
                confidence=0.85,
                rationale="통합 기술 개발 역량이 확인됨",
                evidence_ids=["DEMO-TECH-001"],
            ),
            "market": ScoreDetail(
                dimension="market",
                score=70,
                weight=0.3,
                confidence=0.75,
                rationale="자동화 수요는 있으나 반복 구매 검증이 필요함",
                evidence_ids=["DEMO-MARKET-001"],
            ),
            "financial": ScoreDetail(
                dimension="financial",
                score=60,
                weight=0.3,
                confidence=0.7,
                rationale="런웨이는 있으나 양산 자금이 추가로 필요함",
                evidence_ids=["DEMO-FIN-001"],
            ),
        }
        decision = InvestmentDecision(
            decision="조건부 투자",
            total_score=71,
            confidence=0.77,
            investment_reasons=["기술과 시장 수요의 초기 근거가 확인됨"],
            counter_arguments=["반복 구매와 대량 생산성은 미검증"],
            red_flags=["양산 전 현금 소진 가능성"],
            conditions=["유료 반복 구매 및 장기 운용 지표 확인"],
            evidence_ids=evidence_ids,
        )
        return DecisionResult(decision=decision, scores=scores)

    def write_report(
        profile: CompanyProfile,
        tech: TechAssessment,
        market: MarketAssessment,
        financial: FinancialAssessment,
        decision: InvestmentDecision,
        all_evidence: list[Evidence],
        *,
        scores: dict[str, ScoreDetail] | None = None,
        market_category: MarketCategory | None = None,
    ) -> InvestmentReport:
        return InvestmentReport(
            summary=f"{profile.company_name} 투자 검토 데모 보고서",
            technology=tech.product_summary,
            market_competition="; ".join(market.opportunities + market.market_risks),
            financials=f"{financial.revenue}; {financial.operating_income}",
            risks="; ".join(decision.red_flags),
            decision=f"{decision.decision}: {'; '.join(decision.conditions)}",
            references=[item.evidence_id for item in all_evidence],
        )

    return InvestmentAgents(
        classify_market=classify_market,
        analyze_technology=analyze_technology,
        analyze_market=analyze_market,
        analyze_financials=analyze_financials,
        make_decision=make_decision,
        write_report=write_report,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", default="로브로스")
    parser.add_argument("--company-id", default="company-01")
    parser.add_argument("--query", default="기술·시장·재무를 종합해 투자 여부를 분석해줘")
    parser.add_argument("--as-of-date", default="2026-09-30")
    parser.add_argument("--output", type=Path, help="전체 State JSON 저장 경로")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    graph = build_investment_graph(build_demo_agents(args.company, args.company_id))
    print("LangGraph 실행: classify → (technology ∥ market) → financial → decision → report")
    result = graph.invoke({"query": args.query, "as_of_date": args.as_of_date})
    payload = to_storage_payload(result)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(f"결과 저장: {output}")
    else:
        print(rendered)

    print(
        "완료: "
        f"decision={payload['decision']['decision']}, "
        f"evidence={len(payload['evidence'])}, "
        f"references={len(payload['report']['references'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
