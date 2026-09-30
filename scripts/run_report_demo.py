"""보고서 에이전트(skala_rag.agents.report)를 LangGraph 워크플로우에 끼워 돌려보는 데모.

앞 단계 5개 에이전트는 샘플 기업(Robot One) 데이터를 돌려주는 스텁이고, 보고서 에이전트만 실제 코드다.

    uv run python scripts/run_report_demo.py                 # 가짜 LLM (오프라인, API 호출 없음)
    uv run python scripts/run_report_demo.py --openai        # 실제 OpenAI (OPENAI_API_KEY 필요)
    uv run python scripts/run_report_demo.py --openai --model gpt-4o

보고서는 storage/reports/ 에 Markdown으로 저장된다.
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import date
from pathlib import Path

from skala_rag.agents import AnalysisResult, ClassificationResult, DecisionResult, InvestmentAgents
from skala_rag.agents import report as R
from skala_rag.agents.report import make_report_writer
from skala_rag.graph import build_investment_graph
from skala_rag.models import (
    CompanyProfile, Evidence, FinancialAssessment, InvestmentDecision, MarketAssessment,
    MarketCategory, MissingFact, ScoreDetail, TechAssessment,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
OUT = Path(__file__).resolve().parents[1] / "storage" / "reports"


def ev(eid, claim, grade="B", stance="support", stype="news"):
    return Evidence(evidence_id=eid, claim_text=claim, stance=stance, source_type=stype,
                    source_grade=grade, source_uri=f"https://example.com/{eid}", confidence=0.8)


EVID = {
    "tech": [
        ev("EVD-TECH-1", "Robot One의 비전 기반 피킹 로봇은 2025년 시험에서 시간당 600개 피킹 성공률 99.2%를 기록했다", "B"),
        ev("EVD-TECH-2", "Robot One은 로봇 그리퍼 관련 국내 특허 3건을 등록했다", "A", stype="patent"),
        ev("EVD-TECH-3", "투명·반사 물체 인식 정확도는 85% 수준으로 제한적이다", "B", stance="contradict"),
    ],
    "market": [
        ev("EVD-MKT-1", "국내 물류 자동화 시장은 2025년 약 3조 원 규모로 연 12% 성장 전망이다", "D", stype="market_research"),
        ev("EVD-MKT-2", "Robot One은 국내 3PL 2곳과 유료 PoC 계약을 체결했다고 발표했다", "C", stype="first_party"),
        ev("EVD-MKT-3", "경쟁사 A사는 유사한 피킹 로봇을 대당 1억 원에 판매한다", "B"),
    ],
    "fin": [ev("EVD-FIN-1", "Robot One의 2025년 매출은 12억 원, 영업손실 30억 원이다", "A", stype="regulatory")],
}


def classify(query, as_of):
    return ClassificationResult(
        CompanyProfile(company_id="robot-1", company_name="Robot One", physical_ai_type="industrial_robot",
                       stage="Series A", as_of_date=date.fromisoformat(as_of)),
        MarketCategory(industry="Robotics", sub_industry="Logistics automation",
                       target_market=["물류센터"], customer_type=["B2B"], analysis_scope=[query]))


def technology(profile, category, query):
    return AnalysisResult(TechAssessment(
        product_summary="비전 AI 기반 물류 피킹 로봇", core_technology=["3D 비전", "그리퍼"],
        strengths=["높은 피킹 성공률"], limitations=["투명 물체 인식 한계"], patents=["그리퍼 특허 3건"],
        technical_risks=["비정형 물체 대응"], evidence_ids=[e.evidence_id for e in EVID["tech"]]), EVID["tech"])


def market(profile, category, query):
    return AnalysisResult(MarketAssessment(
        tam="3조 원(2025, 국내 물류 자동화)", competitors=["A사"], traction=["3PL 2곳 유료 PoC"],
        market_risks=["대기업 진입"], evidence_ids=[e.evidence_id for e in EVID["market"]],
        missing_facts=[MissingFact(field="SOM", reason="not_found", sources_checked=["web"])]), EVID["market"])


def finance(profile, tech, mkt):
    return AnalysisResult(FinancialAssessment(
        revenue="12억 원(2025)", operating_income="-30억 원(2025)", financial_risks=["높은 현금 소진"],
        evidence_ids=["EVD-FIN-1"],
        missing_facts=[MissingFact(field="burn_rate", reason="not_disclosed")]), EVID["fin"])


def decide(tech, mkt, fin, evidence):
    return DecisionResult(
        InvestmentDecision(decision="조건부 투자", total_score=67, confidence=0.7,
                           investment_reasons=["검증된 피킹 성능", "특허 기반 방어력"],
                           counter_arguments=["영업손실 규모가 큼"], red_flags=["투명 물체 인식 한계"],
                           conditions=["유료 PoC의 본계약 전환 확인"], evidence_ids=["EVD-TECH-1"]),
        {d: ScoreDetail(dimension=d, score=score, weight=w, confidence=0.7, rationale=why)
         for d, score, w, why in SCORES})


# 설계서 표 7의 6개 평가 항목 (가중합 = 67점)
SCORES = [
    ("창업팀 역량·시장 적합성", 70, 0.15, "로봇 분야 경력 보유, 창업자 이력 근거 부족"),
    ("시장 매력도", 70, 0.15, "국내 물류 자동화 시장 연 12% 성장 전망"),
    ("제품·기술 경쟁력", 80, 0.25, "피킹 성공률 99.2%, 투명 물체 인식은 제한적"),
    ("시장 검증·사업 성과", 55, 0.20, "유료 PoC 2건, 본계약 전환 미확인"),
    ("지속 가능한 경쟁우위", 60, 0.10, "그리퍼 특허 3건"),
    ("확장성·제품당 수익성", 60, 0.15, "영업손실 30억 원, 단위 경제성 미확인"),
]


class FakeLLM:
    """with_structured_output(schema).invoke(messages) → 프롬프트의 첫 근거 ID를 인용한 최소 초안."""

    def with_structured_output(self, schema):
        llm = self

        class _S:
            def invoke(self, messages):
                return llm.draft(schema, messages[1][1])
        return _S()

    def draft(self, schema, prompt):
        ids = re.findall(r"^\s*- (\S+) \| 등급", prompt, re.M) or []
        ids = ids[:1]
        s = lambda t: R.Sentence(text=t, evidence_ids=ids, kind="fact" if ids else "unavailable")  # noqa: E731
        paras = [R.Paragraph(sentences=[s("근거에 따른 서술 문장")])]
        if schema is R.GroundingVerdict:
            n = len(re.findall(r"^\[\d+\] 문장", prompt, re.M))
            return R.GroundingVerdict(judgments=[R.GroundingJudgment(index=i, supported=True) for i in range(n)])
        if schema is R.SummaryDraft:
            return R.SummaryDraft(sentences=[s("요약 문장")])
        if schema is R.DecisionDraft:
            a = R.Argument(text="논거", evidence_ids=ids)
            return R.DecisionDraft(theses=[a], counter_arguments=[a], limitations=["한계"],
                                   risks=[R.Risk(category="기술", likelihood="중간", impact="높음",
                                                 loss_path="손실 경로", indicator="지표", evidence_ids=ids)])
        if schema is R.MarketDraft:
            return R.MarketDraft(paragraphs=paras, size_rows=[R.MarketSizeRow(
                segment="TAM", size="3조 원", base_year="2025", assumption="Top-down", evidence_ids=ids)])
        if schema is R.CompetitionDraft:
            return R.CompetitionDraft(paragraphs=paras, columns=[])
        if schema is R.TeamDraft:
            return R.TeamDraft(paragraphs=paras, rows=[])
        return R.SectionDraft(paragraphs=paras)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--openai", action="store_true", help="가짜 LLM 대신 OpenAI 모델 사용")
    parser.add_argument("--model", default="gpt-4o-mini")
    args = parser.parse_args()
    if args.openai:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=args.model, temperature=0)
    else:
        llm = FakeLLM()
    agents = InvestmentAgents(classify, technology, market, finance, decide,
                              make_report_writer(llm, output_dir=OUT))
    result = build_investment_graph(agents).invoke({"query": "Robot One 분석", "as_of_date": "2026-09-30"})
    print("\n".join(result["report"].references))
    print("saved:", OUT / f"{result['company_profile'].company_id}_{result['company_profile'].as_of_date}.md")


if __name__ == "__main__":
    main()
