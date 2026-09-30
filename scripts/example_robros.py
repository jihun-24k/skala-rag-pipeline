"""로브로스 예시 보고서 → Markdown·PDF → 장수 확인.

실제 LLM 없이 '실제 보고서 분량'을 가늠할 수 있게, 섹션마다 현실적인 길이의 문장을 돌려주는 ScriptedLLM을 쓴다.
근거 내용은 조 노션 기존 계획서의 로브로스 평가 메모를 옮긴 예시이며, 재무 수치는 형식 확인용 가짜 값이다.

    uv run python scripts/example_robros.py          # ScriptedLLM (API 키 불필요)
    uv run python scripts/example_robros.py --real   # OpenAI (OPENAI_API_KEY, langchain-openai 필요)
    PDF 변환: uv pip install markdown pypdf playwright && uv run playwright install chromium
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

from skala_rag.agents.report import (
    Argument, CompetitionDraft, CompetitorColumn, DecisionDraft, GroundingJudgment, GroundingVerdict, MarketDraft,
    MarketSizeRow, Paragraph, Risk, SectionDraft, Sentence, SummaryDraft, TeamDraft, TeamRow, make_report_writer,
    render_markdown,
)
from skala_rag.models import (
    CompanyProfile, Evidence, FinancialAssessment, InvestmentDecision, MarketAssessment, MarketCategory, MissingFact,
    ScoreDetail, TechAssessment,
)


def ev(eid, claim, grade, stype, uri, stance="support", locator=None):
    return Evidence(evidence_id=eid, claim_text=claim, stance=stance, source_type=stype, source_grade=grade,
                    source_uri=uri, locator=locator, confidence=0.8)


EVIDENCE = [
    ev("ROB-TECH-001", "IGRIS-C는 높이 약 154cm, 전체 53 DoF의 성인형 전신 휴머노이드다", "B", "first_party",
       "https://example.com/robros/dev-docs"),
    ev("ROB-TECH-002", "IGRIS-C 무게가 제품 페이지 56kg, 개발자 문서 60kg으로 상충한다", "C", "first_party",
       "https://example.com/robros/igris-c", stance="contradict"),
    ev("ROB-TECH-003", "양팔 합산 가반하중 6kg, 최대 관절토크 150Nm", "B", "first_party",
       "https://example.com/robros/dev-docs"),
    ev("ROB-TECH-004", "PTE는 기본 ACT 대비 블록 분류 작업시간을 7.274초에서 4.024초로 줄이면서 성공률 100%를 유지했다",
       "A", "academic", "https://example.org/act-pte", locator="Table 2"),
    ev("ROB-TECH-005", "VCA는 격자무늬 배경 블록 분류 성공률을 ACT 20%에서 44%로 높였으나 하노이탑은 0%에 그쳤다",
       "A", "academic", "https://example.org/vca", stance="contradict"),
    ev("ROB-TECH-006", "Transformer 충돌감지 정확도 86.4~96.5%는 시뮬레이션과 7축 로봇팔 조건의 결과다", "A",
       "academic", "https://example.org/collision", stance="contradict"),
    ev("ROB-TECH-007", "공개 특허·출원 8건 중 휴머노이드와 직접 관련된 것은 PTE와 데이터 수집 글러브 2건이다", "A",
       "patent", "https://example.org/kipris/robros", stance="contradict"),
    ev("ROB-TECH-008", "VLA·월드모델은 공식 기술 방향이지만 모델 구조·데이터 규모·벤치마크가 공개되지 않았다", "C",
       "first_party", "https://example.com/robros/ai", stance="unknown"),
    ev("ROB-TECH-009", "C+ 모델은 양팔 15~20kg 가반하중을 목표로 한다", "E", "first_party",
       "https://example.com/robros/cplus"),
    ev("ROB-TEAM-001", "핵심 연구자가 IEEE TRO·IJRR·ICRA 등에서 실제 휴머노이드 보행·균형·외력 추정 연구를 수행했다",
       "A", "academic", "https://example.org/scholar/robros"),
    ev("ROB-MKT-001", "회사 발표 기준 누적 생산 36대, 누적 판매 18대", "C", "first_party",
       "https://example.com/robros/news/36units"),
    ev("ROB-MKT-002", "9개 기관에 9대를 유상 납품했다", "C", "first_party", "https://example.com/robros/news/36units"),
    ev("ROB-MKT-003", "반도체·자동차·저온 물류 현장 실증과 물류·조선소 PoC를 수행했다", "B", "counterparty",
       "https://example.org/kiria/humanoid-pilot"),
    ev("ROB-MKT-004", "고객별 계약금액, 재구매, 현장 가동률, 유상 유지보수 계약은 공개되지 않았다", "C", "first_party",
       "https://example.com/robros/news/36units", stance="unknown"),
    ev("ROB-COMP-001", "Agility Robotics는 GXO 계약에서 토트 10만 개 처리 실적을 공개했다", "B", "counterparty",
       "https://example.org/gxo-agility"),
    ev("ROB-COMP-002", "Apptronik은 3.5억 달러를 조달하고 Mercedes-Benz 공장 테스트를 진행했다", "B", "counterparty",
       "https://example.org/apptronik"),
    ev("ROB-FIN-001", "Series A 투자 유치 보도(금액·투자자 미확인)", "D", "independent_media",
       "https://example.org/news/robros-a"),
    ev("ROB-FIN-010", "2025년 매출 12억 원, 영업손실 31억 원, 현금성자산 35억 원(예시 값)", "A", "regulatory",
       "https://example.org/fsc/robros"),
]
TECH_IDS = [e.evidence_id for e in EVIDENCE if "-TECH-" in e.evidence_id or "-TEAM-" in e.evidence_id]
MKT_IDS = [e.evidence_id for e in EVIDENCE if "-MKT-" in e.evidence_id or "-COMP-" in e.evidence_id]


def inputs():
    profile = CompanyProfile(company_id="robros", company_name="로브로스", physical_ai_type="휴머노이드",
                             stage="Series A", as_of_date=date(2026, 9, 30))
    category = MarketCategory(industry="로보틱스", sub_industry="휴머노이드", target_market=["국내 제조·물류 현장"],
                              customer_type=["B2B"])
    tech = TechAssessment(product_summary="IGRIS-C 전신 휴머노이드와 개발자 SDK",
                          core_technology=["전신 제어", "모방학습(PTE)"], technical_risks=["장기 운전 신뢰성 미검증"],
                          evidence_ids=TECH_IDS,
                          missing_facts=[MissingFact(field="MTBF·연속 운전시간", reason="not_disclosed",
                                                     sources_checked=["제품 페이지", "개발자 문서"])])
    market = MarketAssessment(competitors=["Agility Robotics", "Apptronik", "Unitree"],
                              traction=["18대 판매", "9개 기관 유상 납품"], market_risks=["공공 실증 예산 의존"],
                              evidence_ids=MKT_IDS,
                              missing_facts=[MissingFact(field="재구매율", reason="not_disclosed"),
                                             MissingFact(field="TAM·SAM·SOM", reason="not_found",
                                                         sources_checked=["KIRIA", "IFR"])])
    fin = FinancialAssessment(revenue="12억 원(예시)", operating_income="-31억 원(예시)", total_assets="98억 원(예시)",
                              burn_rate="2.5억 원/월(예시)", runway_months=14,
                              financial_risks=["1년 안팎 추가 조달 필요"], evidence_ids=["ROB-FIN-001", "ROB-FIN-010"])
    decision = InvestmentDecision(
        decision="조건부 투자", total_score=64.0, confidence=0.62,
        investment_reasons=[a.text for a in DECISION.theses], counter_arguments=[a.text for a in DECISION.counter_arguments],
        red_flags=["MTBF 미공개"], evidence_ids=["ROB-MKT-002"],
        conditions=["고객사가 확인하는 반복 구매 또는 유상 유지보수 계약", "현장 가동률·MTBF 등 장기 운전 지표 제출",
                    "휴머노이드 핵심 구조 특허 출원 계획"])
    dims = [("창업팀 역량·시장 적합성", 80, .15), ("시장 매력도", 60, .15), ("제품·기술 경쟁력", 80, .25),
            ("시장 검증·사업 성과", 40, .20), ("지속 가능한 경쟁우위", 60, .10), ("확장성·제품당 수익성", 60, .15)]
    scores = {d: ScoreDetail(dimension=d, score=s, weight=w, confidence=0.6, rationale="예시") for d, s, w in dims}
    return (profile, tech, market, fin, decision, EVIDENCE), {"scores": scores, "market_category": category}


def S(text, *ids, kind="fact"):
    return Sentence(text=text, evidence_ids=list(ids), kind=kind)


def P(*sentences):
    return Paragraph(sentences=list(sentences))


SECTIONS = {
    "3. BUSINESS IDEA": SectionDraft(paragraphs=[
        P(S("로브로스는 반도체·자동차·저온 물류처럼 인력 확보가 어렵고 반복 작업이 많은 현장을 목표 고객으로 삼는다", "ROB-MKT-003"),
          S("실제 비용 지불자는 현장 자동화 예산을 가진 제조·물류 기업과 실증사업을 운영하는 공공기관이다", "ROB-MKT-002", "ROB-MKT-003"),
          S("고객은 기존 고정형 자동화로 대응하기 어려운 비정형 작업을 전신 휴머노이드로 대체하려는 수요를 가진다", "ROB-MKT-003", kind="estimate")),
        P(S("회사는 IGRIS-C 하드웨어와 개발자 SDK를 함께 제공해 고객이 현장 작업을 직접 학습시키는 구조를 제시한다", "ROB-TECH-001"),
          S("제품 단계는 9개 기관 유상 납품이 확인된 초기 상용화 단계로 볼 수 있다", "ROB-MKT-002"),
          S("다만 과금 방식, 대당 가격, 유지보수 매출 비중은 공개되지 않아 비즈니스 모델의 반복성은 확인 불가다", "ROB-MKT-004"),
          S("현재 매출은 연구·실증 목적의 기관 납품 비중이 높아 특정 고객군 의존도가 클 가능성이 있다", "ROB-MKT-002", "ROB-MKT-003", kind="estimate"))]),
    "4. PRODUCT & TECHNOLOGY": SectionDraft(paragraphs=[
        P(S("IGRIS-C는 높이 약 154cm, 53 DoF의 전신 휴머노이드로 센서·제어·통신을 하나의 플랫폼으로 통합했다", "ROB-TECH-001"),
          S("양팔 합산 가반하중은 6kg, 최대 관절토크는 150Nm로 산업용 중량 작업에는 제한적이다", "ROB-TECH-003"),
          S("모방학습 PTE는 양팔 블록 분류 단일 작업에서 작업시간을 7.274초에서 4.024초로 줄이면서 성공률 100%를 유지했다", "ROB-TECH-004"),
          S("반면 VCA는 격자무늬 배경에서 성공률을 44%까지 높였지만 하노이탑 과제는 0%에 그쳐 일반화 범위가 좁다", "ROB-TECH-005")),
        P(S("공개 특허·출원 8건 중 휴머노이드와 직접 관련된 것은 2건뿐이어서 구현 역량에 비해 법적 방어력이 약하다", "ROB-TECH-007"),
          S("충돌감지 연구의 정확도 86.4~96.5%는 시뮬레이션과 7축 로봇팔 조건 결과로 전신 제품의 안전성을 입증하지 않는다", "ROB-TECH-006"),
          S("VLA·월드모델은 공식 기술 방향이지만 구조·데이터·벤치마크가 공개되지 않아 현재 평가에는 반영하지 않았다", "ROB-TECH-008"),
          S("제품 페이지와 개발자 문서의 무게가 56kg과 60kg으로 달라 버전별 사양 관리가 불명확하다", "ROB-TECH-002"))]),
    "6. COMPETITION & MOAT": CompetitionDraft(
        columns=[
            CompetitorColumn(name="로브로스", kind="대상 기업", customers="국내 제조·물류·공공 실증", features="전신 휴머노이드 + SDK",
                             price="확인 불가", strengths="유상 납품·논문 기반 제어", weaknesses="운영지표·특허 부족",
                             switching_cost="확인 불가", evidence_ids=["ROB-MKT-002", "ROB-TECH-007"]),
            CompetitorColumn(name="Agility Robotics", kind="경쟁사", customers="글로벌 물류(GXO)", features="물류용 이족 로봇",
                             price="확인 불가", strengths="현장 처리 실적 공개", weaknesses="국내 진출 미확인",
                             switching_cost="확인 불가", evidence_ids=["ROB-COMP-001"]),
            CompetitorColumn(name="Apptronik", kind="경쟁사", customers="완성차 공장", features="범용 휴머노이드",
                             price="확인 불가", strengths="대규모 자금 조달", weaknesses="양산 실적 미확인",
                             switching_cost="확인 불가", evidence_ids=["ROB-COMP-002"]),
            CompetitorColumn(name="수작업·고정형 자동화", kind="기존 대안", customers="-", features="-", price="확인 불가",
                             strengths="검증된 신뢰성", weaknesses="인력난·유연성 부족", switching_cost="확인 불가")],
        paragraphs=[P(
            S("로브로스의 현재 우위는 국내에서 빠르게 제품화해 유상 납품까지 이어간 실행 속도다", "ROB-MKT-002"),
            S("글로벌 경쟁사는 현장 처리량과 대규모 조달 실적을 공개하고 있어 운영 지표 면에서 격차가 있다", "ROB-COMP-001", "ROB-COMP-002"),
            S("핵심 구조 특허가 적어 하드웨어 설계는 경쟁사가 비교적 빠르게 추격할 수 있는 요소다", "ROB-TECH-007"),
            S("지속 가능한 진입장벽은 연구진의 보행·균형 제어 역량과 현장 데이터 축적에서 나올 가능성이 크다", "ROB-TEAM-001", kind="estimate"),
            S("글로벌 기업이 국내에 진입하면 가격 경쟁으로 대당 수익성이 압박받을 수 있다", "ROB-COMP-002", kind="estimate"))]),
    "7. TRACTION": SectionDraft(paragraphs=[
        P(S("회사 발표 기준 누적 생산 36대, 누적 판매 18대로 수제작 시제품 단계는 벗어났다", "ROB-MKT-001"),
          S("9개 기관에 9대를 유상 납품해 기관당 1대 수준의 초기 도입이 확인된다", "ROB-MKT-002"),
          S("반도체·자동차·저온 물류 실증과 물류·조선소 PoC가 공공 실증사업 자료로 확인된다", "ROB-MKT-003")),
        P(S("다만 고객별 계약금액, 재구매, 현장 가동률, 유상 유지보수 계약은 공개되지 않았다", "ROB-MKT-004"),
          S("PoC가 민간 유료 계약으로 전환됐는지와 보조금 의존도는 현재 자료로 판단할 수 없다", "ROB-MKT-004"),
          S("따라서 판매 대수는 상용화 신호로 인정하되 반복 가능한 성장 방식이 입증됐다고 보지는 않았다", "ROB-MKT-001", "ROB-MKT-004", kind="estimate"))]),
    "8. TEAM": TeamDraft(
        rows=[TeamRow(person="핵심 연구진", role="제어·보행 연구", experience="IEEE TRO·IJRR 등 실제 휴머노이드 보행·균형 연구",
                      assessment="진입장벽이 높은 전신 제어 역량 보유", evidence_ids=["ROB-TEAM-001"]),
              TeamRow(person="모방학습 연구팀", role="AI·조작", experience="ACT-PTE, VCA 실물 양팔 실험",
                      assessment="응용 연구 역량은 확인, 범용 AI는 미입증", evidence_ids=["ROB-TECH-004", "ROB-TECH-005"])],
        paragraphs=[P(
            S("연구진은 휴머노이드 보행·균형·외력 추정 분야에서 장기간 실물 실험 기반 연구를 수행해 기술 측면의 적합성은 높다", "ROB-TEAM-001"),
            S("논문에서 제품으로 이어진 PTE 사례는 연구 성과를 사업화하는 실행 경로를 보여준다", "ROB-TECH-004"),
            S("창업자·기술책임자의 이력 근거가 없어 Founder-Market Fit과 경영진 역할 분담은 확인 불가이며 추가 실사가 필요하다", kind="unavailable"))]),
    "9. FINANCIALS": SectionDraft(paragraphs=[
        P(S("영업손실 규모가 매출을 크게 웃돌아 현재는 연구개발과 생산 투자에 비용이 집중된 구조다",
            "ROB-FIN-010", kind="estimate"),
          S("공시 기준 재무제표가 확보돼 재무 게이트는 통과했지만 재무자료의 감사 여부는 확인 불가다", kind="unavailable"),
          S("투자 라운드 금액과 투자자는 언론 보도만 있어 누적 투자금은 확정할 수 없다", "ROB-FIN-001"),
          S("현금성자산과 월 소진액을 보면 다음 조달이 1년 안팎에 필요하며 조달 실패 시 생산 확대가 지연될 수 있다",
            "ROB-FIN-010", kind="estimate"))]),
    "10. VALUATION": SectionDraft(paragraphs=[
        P(S("상장 비교기업 대비 가치평가는 라운드 조건과 비교 배수가 공개되지 않아 확인 불가다", kind="unavailable"),
          S("글로벌 경쟁사의 대규모 조달 사례는 휴머노이드 시장의 자금 유입을 보여주지만 로브로스 가치의 직접 근거는 아니다", "ROB-COMP-002"))]),
}
MARKET = MarketDraft(
    size_rows=[MarketSizeRow(segment="TAM", size="확인 불가", base_year="-", assumption="휴머노이드 시장 정의별 전망 편차가 커 단일 값 미채택"),
               MarketSizeRow(segment="SAM", size="확인 불가", base_year="-", assumption="국내 제조·물류 현장 휴머노이드 도입 예산"),
               MarketSizeRow(segment="SOM", size="확인 불가", base_year="-", assumption="실증 참여 기관 수 × 기관당 도입 대수(Bottom-up)")],
    paragraphs=[P(
        S("로브로스가 실제 진입하는 시장은 국내 제조·물류 현장의 비정형 반복 작업용 전신 휴머노이드 시장이다", "ROB-MKT-003"),
        S("공공 실증사업으로 반도체·자동차·저온 물류 현장의 도입 수요가 확인되고 있다", "ROB-MKT-003"),
        S("시장 규모는 정의(연구용·산업용·서비스용 포함 여부)에 따라 크게 달라 검증된 단일 수치를 채택하지 않았다", kind="unavailable"),
        S("글로벌 경쟁사의 대규모 조달과 공장 테스트는 산업용 휴머노이드 수요가 형성되고 있다는 Why Now 신호다", "ROB-COMP-002"))])
DECISION = DecisionDraft(
    theses=[Argument(text="논문·하드웨어·유상 납품으로 기술 실재성이 확인돼, 조건 충족 시 국내 산업용 휴머노이드 선도 기업으로 가치가 재평가될 수 있다", evidence_ids=["ROB-TECH-004", "ROB-MKT-002"]),
            Argument(text="진입장벽이 높은 보행·균형 제어 역량을 연구진이 보유해 후발 주자 대비 기술 격차를 유지할 수 있다", evidence_ids=["ROB-TEAM-001"]),
            Argument(text="누적 36대 생산으로 소량 반복생산 능력을 확보해 양산 투자 시 매출 확대 경로가 존재한다", evidence_ids=["ROB-MKT-001"])],
    counter_arguments=[Argument(text="판매 대수 외 가동률·재구매·계약금액이 없어 시장 적합성이 입증되지 않았고, 연구기관 수요가 민간 수요로 이어지지 않을 수 있다", evidence_ids=["ROB-MKT-004"]),
                       Argument(text="대규모 자금을 조달한 글로벌 경쟁사가 운영 실적을 먼저 쌓고 있어 국내 우위가 가격 경쟁에서 빠르게 약해질 수 있다", evidence_ids=["ROB-COMP-001", "ROB-COMP-002"])],
    risks=[Risk(category="기술", likelihood="중간", impact="높음", loss_path="장기 운전 신뢰성이 낮으면 현장 재구매가 끊겨 매출이 실증 단계에 머문다", indicator="MTBF·가동률 공개 여부", evidence_ids=["ROB-MKT-004"]),
           Risk(category="경쟁", likelihood="높음", impact="높음", loss_path="글로벌 경쟁사 국내 진입 시 가격 인하 압력으로 대당 마진이 악화된다", indicator="해외 업체 국내 수주 동향", evidence_ids=["ROB-COMP-001", "ROB-COMP-002"]),
           Risk(category="기술", likelihood="중간", impact="중간", loss_path="핵심 구조 특허가 적어 설계 복제 시 차별성이 약해진다", indicator="휴머노이드 구조 특허 출원 수", evidence_ids=["ROB-TECH-007"]),
           Risk(category="시장", likelihood="중간", impact="중간", loss_path="공공 실증 예산이 줄면 초기 수요가 급감한다", indicator="민간 유료 계약 비중", evidence_ids=["ROB-MKT-003"]),
           Risk(category="팀·재무", likelihood="중간", impact="높음", loss_path="후속 조달이 늦어지면 생산 확대와 인력 채용이 중단된다", indicator="다음 라운드 착수 시점", evidence_ids=["ROB-FIN-001"])],
    limitations=["회사 발표 자료 의존도가 높아 트랙션 수치의 독립 검증이 부족하며, 사업 성과 점수가 과대평가됐을 수 있다.",
                 "고객 인터뷰를 수행하지 않아 도입 효과와 재구매 의향을 판단에 반영하지 못했다.",
                 "재무자료의 감사 여부가 확인되지 않아 런웨이 추정에 오차가 있을 수 있다.",
                 "시장 규모 전망의 정의 차이로 TAM·SAM·SOM을 산정하지 못해 기대수익 규모를 정량화하지 못했다."])
SUMMARY = SummaryDraft(sentences=[
    S("로브로스는 국내 제조·물류 현장의 비정형 반복 작업을 전신 휴머노이드 IGRIS-C로 자동화하는 기업이다", "ROB-MKT-003", "ROB-TECH-001"),
    S("정량 실험이 있는 모방학습 논문, 53 DoF 전신 플랫폼, 9개 기관 유상 납품이 기술 실재성을 뒷받침한다", "ROB-TECH-004", "ROB-TECH-001", "ROB-MKT-002"),
    S("연구진의 보행·균형 제어 역량은 후발 주자 대비 기술 격차의 원천이다", "ROB-TEAM-001"),
    S("다만 가동률·재구매·계약금액이 공개되지 않았고 휴머노이드 핵심 구조 특허가 적다", "ROB-MKT-004", "ROB-TECH-007"),
    S("투자 라운드 조건과 기업가치는 확인 불가다", kind="unavailable"),
    S("따라서 반복 구매와 장기 운전 지표 확인을 조건으로 조건부 투자를 제시한다", "ROB-MKT-004")])


class ScriptedLLM:
    """섹션 제목을 보고 준비된 초안을 돌려준다. 근거 일치 검사는 모두 통과시킨다."""

    def with_structured_output(self, schema):
        return _Runner(schema)


class _Runner:
    def __init__(self, schema):
        self.schema = schema

    def invoke(self, messages):
        prompt = messages[1][1]
        if self.schema is GroundingVerdict:
            n = len(re.findall(r"^\[(\d+)\] 문장:", prompt, re.M))
            return GroundingVerdict(judgments=[GroundingJudgment(index=i, supported=True) for i in range(n)])
        if self.schema is MarketDraft:
            return MARKET
        if self.schema is DecisionDraft:
            return DECISION
        if self.schema is SummaryDraft:
            return SUMMARY
        return SECTIONS[re.search(r"\[작성할 섹션\] (.+)", prompt).group(1).strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="OpenAI로 실제 생성")
    parser.add_argument("--no-pdf", action="store_true", help="Markdown만 만들기")
    args = parser.parse_args()
    if args.real:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    else:
        llm = ScriptedLLM()
    out_dir = Path("storage/reports")
    positional, extra = inputs()
    report = make_report_writer(llm, output_dir=out_dir)(*positional, **extra)
    md = out_dir / "robros_2026-09-30.md"
    print(f"Markdown: {md} ({len(render_markdown(report)):,}자, 참고문헌 {len(report.references)}개)")
    if args.no_pdf:
        return
    from export_pdf import PAGE_LIMIT, export  # 선택 의존성(markdown, pypdf, playwright)

    res = export(md)
    cont, per = res["continuous"][1], res["per-page"][1]
    print(f"이어서 배치: {cont}쪽 → {res['continuous'][0]}")
    print(f"설계 페이지별 배치: {per}쪽 → {res['per-page'][0]}")
    print(f"판정: {PAGE_LIMIT}페이지 제한 {'충족' if cont <= PAGE_LIMIT else '초과'}")


if __name__ == "__main__":
    main()
