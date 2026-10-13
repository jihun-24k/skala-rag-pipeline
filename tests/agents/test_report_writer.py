"""write_report(ReportWriter 구현) 테스트.

LLM 호출 없이 FakeLLM으로 인용 규칙·섹션 구성·그래프 연결을 검증한다.
"""

from __future__ import annotations

import re
from datetime import date

from skala_rag.agents import AnalysisResult, ClassificationResult, DecisionResult, InvestmentAgents
from skala_rag.agents.report import (
    Argument, CompetitionDraft, CompetitorColumn, DecisionDraft, GroundingJudgment, GroundingVerdict, MarketDraft,
    MarketSizeRow, Paragraph, Risk, SectionDraft, Sentence, SummaryDraft, TeamDraft, TeamRow, _suffix_same_year,
    build_evaluation_report, make_report_writer, render_markdown,
)
from skala_rag.graph import build_investment_graph
from skala_rag.models import (
    CompanyProfile, Evidence, FinancialAssessment, InvestmentDecision, InvestmentReport, MarketAssessment,
    MarketCategory, MissingFact, ScoreDetail, TechAssessment,
)

ID_RE = re.compile(r"^- ([A-Za-z0-9_\-]+) \|", re.M)


# ── FakeLLM: 첫 시도에는 규칙 위반 문장을 섞어 재작성·제외 로직을 시험한다 ──────────
class FakeLLM:
    def __init__(self):
        self.calls = 0

    def with_structured_output(self, schema):
        return _Runner(self, schema)


class _Runner:
    def __init__(self, llm, schema):
        self.llm, self.schema = llm, schema

    def invoke(self, messages):
        self.llm.calls += 1
        prompt, retry = messages[1][1], len(messages) > 2
        first = ID_RE.findall(prompt)[:1]
        bad = [] if retry else [Sentence(text="업계 최고 수준으로 성공률 99%를 달성했다.", evidence_ids=[]),
                                Sentence(text="시장 점유율이 높다.", evidence_ids=["FAKE-ID-999"])]
        s = self.schema
        if s is GroundingVerdict:
            items = re.findall(r"^\[(\d+)\] 문장: (.*)$", prompt, re.M)
            return GroundingVerdict(judgments=[GroundingJudgment(index=int(i), supported="범용" not in t,
                                                                 reason="근거보다 과장") for i, t in items])
        body = [Sentence(text="근거 기반 설명 문장이다.", evidence_ids=first),
                Sentence(text="이 기술은 범용 조작지능을 입증했다.", evidence_ids=first),
                Sentence(text="고장률·가동률 지표는 자료 미제공이다.", kind="unavailable"), *bad]
        if s is SectionDraft:
            return SectionDraft(paragraphs=[Paragraph(sentences=body)])
        if s is MarketDraft:
            return MarketDraft(size_rows=[MarketSizeRow(segment="TAM", size="약 10조 원", base_year="2025",
                                                        assumption="국내 로봇산업(Top-down)", evidence_ids=first)],
                               paragraphs=[Paragraph(sentences=body)])
        if s is CompetitionDraft:
            return CompetitionDraft(columns=[
                CompetitorColumn(name="로브로스", kind="대상 기업", customers="국내 제조·물류", features="휴머노이드",
                                 price="확인 불가", strengths="유상 납품", weaknesses="운영지표 미공개",
                                 switching_cost="확인 불가", evidence_ids=first),
                CompetitorColumn(name="Unitree", kind="경쟁사", customers="연구·교육", features="저가 휴머노이드",
                                 price="약 1.6만 달러", strengths="가격", weaknesses="산업 적용",
                                 switching_cost="낮음")], paragraphs=[Paragraph(sentences=body)])
        if s is TeamDraft:
            return TeamDraft(rows=[TeamRow(person="CTO", role="기술책임자", experience="보행 연구",
                                           assessment="핵심 역량", evidence_ids=first),
                                   TeamRow(person="근거없는 인물", role="-", experience="-", assessment="-")],
                             paragraphs=[Paragraph(sentences=body)])
        if s is DecisionDraft:
            return DecisionDraft(
                theses=[Argument(text="유상 납품으로 프로토타입 단계를 벗어났다.", evidence_ids=["EVD-004"]),
                        Argument(text="근거 없는 논거 30% 성장.")],
                counter_arguments=[Argument(text="장기 운전 신뢰성 지표가 없다.", evidence_ids=first)],
                risks=[Risk(category="기술", likelihood="중간", impact="높음", loss_path="고장률이 높으면 재구매가 끊긴다",
                            indicator="MTBF 공개 여부", evidence_ids=first)],
                limitations=["회사 발표 자료 의존도가 높다.", "고객 인터뷰가 없다.", "재무자료 감사 여부 미확인."])
        if s is SummaryDraft:
            return SummaryDraft(sentences=[
                Sentence(text="로브로스는 전신 휴머노이드로 현장 반복 작업을 자동화한다.", evidence_ids=first),
                Sentence(text="본문에 없던 근거를 끌어온 문장이다.", evidence_ids=["EVD-099"]), *bad])
        raise AssertionError(s)


# ── 팀 모델로 만든 입력 ──────────────────────────────────────────
def ev(eid, claim, grade="C", stance="support", stype="first_party", uri=None, locator=None):
    return Evidence(evidence_id=eid, claim_text=claim, stance=stance, source_type=stype, source_grade=grade,
                    source_uri=uri or f"https://example.com/{eid}", locator=locator, confidence=0.8)


EVIDENCE = [
    ev("EVD-001", "PTE는 블록 분류 작업시간을 7.274초에서 4.024초로 단축", "A", stype="academic", locator="Table 2"),
    ev("EVD-002", "제품 페이지 56kg, 개발자 문서 60kg으로 상충", stance="contradict"),
    ev("EVD-003", "C+ 양팔 15~20kg 가반하중 목표", "E"),
    ev("EVD-004", "9개 기관에 9대 유상 납품"),
    ev("EVD-005", "국내 로봇산업 규모 2025년 약 10조 원", "A", stype="regulatory", locator="p.12"),
    ev("EVD-006", "2025년 매출 12억 원", "A", stype="regulatory"),
    ev("EVD-099", "다른 기업 근거", "A"),
]


def inputs(decision="조건부 투자"):
    profile = CompanyProfile(company_id="robros", company_name="로브로스", physical_ai_type="휴머노이드",
                             stage="Series A", as_of_date=date(2026, 9, 30))
    tech = TechAssessment(product_summary="IGRIS-C 전신 휴머노이드", core_technology=["전신 제어", "모방학습"],
                          technical_risks=["장기 운전 신뢰성 미검증"], evidence_ids=["EVD-001", "EVD-002", "EVD-003"],
                          missing_facts=[MissingFact(field="MTBF", reason="not_disclosed",
                                                     sources_checked=["제품 페이지", "개발자 문서"])])
    market = MarketAssessment(tam="약 10조 원(2025)", competitors=["레인보우로보틱스", "Unitree"],
                              traction=["9개 기관 9대 유상 납품"], evidence_ids=["EVD-004", "EVD-005"],
                              missing_facts=[MissingFact(field="재구매율", reason="not_disclosed")])
    fin = FinancialAssessment(revenue="12억 원", operating_income="-31억 원", total_assets="98억 원",
                              burn_rate="2.5억 원", runway_months=14, evidence_ids=["EVD-006"])
    dec = InvestmentDecision(decision=decision, total_score=64.0, confidence=0.62,
                             investment_reasons=["유상 납품으로 프로토타입 단계를 벗어났다"],
                             counter_arguments=["장기 운전 신뢰성 지표가 없다"], red_flags=["MTBF 미공개"],
                             conditions=["고객사 확인 가능한 반복 구매 계약"], evidence_ids=["EVD-004"])
    return profile, tech, market, fin, dec, EVIDENCE


SCORES = {
    "team": ScoreDetail(dimension="창업팀 역량·시장 적합성", score=80, weight=0.15, confidence=0.7, rationale="-"),
    "market": ScoreDetail(dimension="시장 매력도", score=60, weight=0.15, confidence=0.7, rationale="-"),
    "product": ScoreDetail(dimension="제품·기술 경쟁력", score=80, weight=0.25, confidence=0.7, rationale="-"),
    "traction": ScoreDetail(dimension="시장 검증·사업 성과", score=40, weight=0.20, confidence=0.7, rationale="-"),
    "moat": ScoreDetail(dimension="지속 가능한 경쟁우위", score=60, weight=0.10, confidence=0.7, rationale="-"),
    "scalability": ScoreDetail(dimension="확장성·제품당 수익성", score=60, weight=0.15, confidence=0.7, rationale="-"),
}


def write(**kw):
    return make_report_writer(FakeLLM(), **kw)(*inputs(), scores=SCORES)


# ── 테스트 ──────────────────────────────────────────────────────
def test_returns_team_investment_report():
    report = write()
    assert isinstance(report, InvestmentReport)
    assert report.summary.startswith("# 로브로스 투자 평가 보고서") and "조건부 투자" in report.summary
    assert "## 12. INVESTMENT DECISION" in report.decision and "## 11. KEY RISKS" in report.risks


def test_citations_ordered_and_only_used_sources():
    report = write()
    md = render_markdown(report)
    body = md.split("## 14. REFERENCE")[0]
    first_seen = list(dict.fromkeys(int(n) for n in re.findall(r"\[(\d+)\]", body)))
    assert first_seen == list(range(1, len(first_seen) + 1))
    assert [r.split("]")[0] + "]" for r in report.references] == [f"[{n}]" for n in first_seen]
    assert "⟦" not in md and "[[" not in md


def test_unsupported_claims_are_removed():
    md = render_markdown(write())
    assert "99%" not in md and "30% 성장" not in md and "FAKE-ID" not in md
    assert "본문에 없던 근거" not in md          # SUMMARY는 본문 근거만
    assert "범용 조작지능" not in md             # 근거 일치 검사(Self-RAG)
    assert "example.com/EVD-099" not in md     # 어느 분석도 인용하지 않은 근거
    assert "C+ 양팔" in md and "EVD-003" not in md  # E 등급은 로드맵으로만


def test_guideline_sections_and_tables():
    report = write()
    assert "| 제품·기술 경쟁력 | 25% | 80/100 | 20.0 | ✓ |" in report.summary
    assert "| Pre-money 기업가치 | 확인 불가 |" in report.summary  # 없는 항목도 표에 남김
    assert "| 가격 | 확인 불가 | 확인 불가 |" in report.market_competition and "1.6만 달러" not in report.market_competition
    assert "근거없는 인물" not in report.financials and "| 구분 | 인물 | 역할 |" in report.financials
    assert "| 창업자 | 확인 불가 |" in report.financials          # 근거 없어도 창업자 행은 남김
    assert "| 기술책임자 | CTO" in report.financials
    assert "### 10.3 투자수익 시나리오" in report.financials
    assert "MTBF" in report.decision and "회사 미공개" in report.decision  # MissingFact 표
    assert "(회사 주장)" in render_markdown(report)
    assert any("(p.12)" in r or "(Table 2)" in r for r in report.references)


def test_works_without_optional_kwargs_and_other_decisions():
    for decision in ("투자", "추가 실사", "투자 제외"):
        report = make_report_writer(FakeLLM())(*inputs(decision))
        assert f"투자 의견: **{decision}**" in report.summary
        assert "항목별 점수 확인 불가 (총점 64.0점)" in report.summary


def test_retry_once_per_section():
    llm = FakeLLM()
    make_report_writer(llm, verify_grounding=False)(*inputs(), scores=SCORES)
    assert llm.calls == 20  # (본문 8 + 판단 1 + 요약 1) × (최초 + 재작성 1회)


def test_saves_markdown(tmp_path):
    write(output_dir=tmp_path)
    assert (tmp_path / "robros_2026-09-30.md").read_text(encoding="utf-8").startswith("# 로브로스")


def test_same_author_year_suffix():
    refs = ["한국은행(2024). *A*. https://a", "KIRIA(2025). *X*. https://b", "한국은행(2024). *B*. https://c"]
    assert _suffix_same_year(refs) == ["한국은행(2024a). *A*. https://a", "KIRIA(2025). *X*. https://b",
                                       "한국은행(2024b). *B*. https://c"]


def test_plugs_into_team_graph():
    profile, tech, market, fin, dec, evidence = inputs()
    agents = InvestmentAgents(
        classify_market=lambda q, d: ClassificationResult(profile, MarketCategory(industry="로보틱스",
                                                                                  sub_industry="휴머노이드")),
        analyze_technology=lambda p, c, q: AnalysisResult(tech, evidence[:3]),
        analyze_market=lambda p, c, q: AnalysisResult(market, evidence[3:5]),
        analyze_financials=lambda p, t, m: AnalysisResult(fin, evidence[5:]),
        make_decision=lambda t, m, f, e: DecisionResult(dec, SCORES),
        write_report=make_report_writer(FakeLLM()),
    )
    result = build_investment_graph(agents).invoke({"query": "로브로스 분석", "as_of_date": "2026-09-30"})
    report = result["report"]
    assert isinstance(report, InvestmentReport) and report.summary.startswith("# 로브로스")
    assert report.references


def test_team_table_founder_row():
    from skala_rag.agents.report import CitationRegistry, QC, Renderer, _team_table

    rnd = Renderer(CitationRegistry([{"evidence_id": "E1", "claim": "c", "grade": "C", "source_url": "u"}]), QC())
    draft = TeamDraft(rows=[TeamRow(person="홍길동", role="대표이사", experience="-", assessment="-", evidence_ids=["E1"]),
                            TeamRow(person="연구원", role="제어", experience="-", assessment="-", evidence_ids=["E1"])],
                      paragraphs=[])
    table = _team_table(draft, rnd)
    assert "| 창업자 | 홍길동" in table            # slot 없이도 '대표이사'로 창업자 판별
    assert "| 기술책임자 | 확인 불가 |" in table and "| 기타 핵심인력 | 연구원" in table


def evaluation_state():
    from skala_rag.models.orchestration import CitedClaim, EvaluationSummary, PerspectiveResult

    profile, *_ = inputs()
    research = PerspectiveResult(view='technology', findings=[
        CitedClaim(text='블록 분류 작업에서 시간이 단축됐다.', evidence_ids=['EVD-001']),
        CitedClaim(text='제품 페이지와 개발자 문서의 무게가 서로 다르다.', evidence_ids=['EVD-002']),
    ], missing_facts=[MissingFact(field='장기 가동률', reason='공개 자료 미확보',
        sources_checked=['개발자 문서'], attempted_queries=['로브로스 장기 가동률'])])
    compressed = research.model_copy(deep=True)
    compressed.findings = compressed.findings[:1]
    return dict(company_profile=profile, as_of_date='2026-09-30', analysis_revision=2,
        evidence=EVIDENCE[:2], perspectives={'technology': research}, quality_result=None,
        evaluation_summary=EvaluationSummary(perspectives=[compressed],
            limitations=['장기 운영 신뢰성을 확정할 수 없음'], analysis_revision=2))


def test_evaluation_writer_restores_details_lost_in_synthesis_without_mutating_state():
    state = evaluation_state()
    import copy
    before = copy.deepcopy(state)
    report = build_evaluation_report(state, ['검증 조건과 한계를 상세히 작성'])
    tech = next(p for p in report.perspectives if p.view == 'technology')
    assert len(tech.findings) == 2  # 종합 요약에서 빠진 반대·상충 근거도 보존
    assert report.references['EVD-002'] == EVIDENCE[1].source_uri
    assert report.analysis_revision == 2
    assert '로브로스' in report.summary and '생성 모델 없이' in report.summary
    assert state == before


def test_evaluation_writer_supplies_full_evidence_and_rewrite_instructions():
    from skala_rag.models.orchestration import EvaluationReport

    state = evaluation_state()
    calls = []
    def generate(schema, instruction, payload):
        calls.append((instruction, payload))
        assert issubclass(schema, EvaluationReport)
        return payload['draft']

    report = build_evaluation_report(state, ['무게의 상충을 설명'], generate)
    instruction, payload = calls[0]
    assert payload['evidence'][1]['claim_text'] == EVIDENCE[1].claim_text
    assert payload['evidence'][1]['source_uri'] == EVIDENCE[1].source_uri
    assert len(payload['research_perspectives'][0]['findings']) == 2
    assert payload['instructions'] == ['무게의 상충을 설명']
    assert '시험 과제·조건·결과' in instruction and '근거가 부족하면' in instruction
    assert report.analysis_revision == 2


def test_evaluation_body_exposes_missing_fact_searches_and_preserves_headings(tmp_path):
    from skala_rag.agents.report import render_evaluation_perspective
    from skala_rag.pdf_report import render_evaluation_pdf
    from skala_rag.runtime import render_evaluation_markdown
    from pypdf import PdfReader

    report = build_evaluation_report(evaluation_state(), [])
    text = render_evaluation_perspective(report.perspectives[0])
    assert '확인한 자료: 개발자 문서' in text
    assert '조사한 질문:' not in text
    assert report.perspectives[0].missing_facts[0].attempted_queries == ['로브로스 장기 가동률']
    markdown = render_evaluation_markdown(report)
    assert markdown.startswith('# 로브로스 평가 보고서') and '## 14. REFERENCE' in markdown
    pdf = render_evaluation_pdf(report, tmp_path / 'evaluation.pdf')
    reader = PdfReader(pdf)
    pdf_text = '\n'.join(p.extract_text() for p in reader.pages)
    assert len(reader.pages) <= 10 and '장기 가동률' in pdf_text
    assert 'SUMMARY' in pdf_text and 'REFERENCE' in pdf_text
    assert '로브로스 평가 보고서' in pdf_text
    assert reader.metadata.title == '로브로스 평가 보고서'
    from skala_rag.models.orchestration import REPORT_OUTLINE
    for _, title in REPORT_OUTLINE:
        assert '## ' + title in markdown and title in pdf_text
    assert markdown.index('13. LIMITATIONS') < markdown.index('14. REFERENCE')


def test_financial_charts_are_provider_grounded_and_rendered_in_financials(tmp_path):
    from skala_rag.models.investment import Evidence, FinancialObservation
    from skala_rag.models.orchestration import EvaluationReport
    from skala_rag.agents.report import attach_financial_charts, default_evaluation_sections, evaluation_claims
    from skala_rag.pdf_report import render_evaluation_pdf
    from pypdf import PdfReader
    report = EvaluationReport(company_name='테스트 기업', summary='검증용 가상 수치', perspectives=[], analysis_revision=1)
    report.sections = default_evaluation_sections(report)
    evidence = {str(year): Evidence(evidence_id=str(year), claim_text='fixture', stance='support',
        source_type='regulatory', source_grade='A', source_uri='https://example.test/filing',
        company_id='fixture', value=value, financial_observation=FinancialObservation(
            metric='operating_income', period_end=f'{year}-12-31', unit='KRW', statement_scope='separate'))
        for year, value in [(2024, -100), (2025, 200)]}
    report = attach_financial_charts(report, evidence)
    assert len(report.financial_charts) == 1
    assert [p.value for p in report.financial_charts[0].points] == [-100, 200]
    assert {eid for c in evaluation_claims(report) for eid in c.evidence_ids} == {'2024', '2025'}
    path = render_evaluation_pdf(report, tmp_path / 'chart.pdf')
    pages = PdfReader(path).pages
    text = '\n'.join(p.extract_text() for p in pages)
    assert len(pages) <= 10
    assert text.index('9. FINANCIALS') < text.index('영업이익 연도별 변화') < text.index('10. VALUATION')
    assert '-100' in text and '200' in text
    evidence['2025'].financial_observation.statement_scope = 'consolidated'
    assert not attach_financial_charts(report, evidence).financial_charts
    assert not attach_financial_charts(report, {}).financial_charts


def test_classification_is_preserved_even_when_writer_omits_it():
    from skala_rag.models import MarketCategory
    from skala_rag.runtime import render_evaluation_markdown
    state = evaluation_state()
    state['market_category'] = MarketCategory(industry='로봇', sub_industry='휴머노이드',
        target_market=['제조'], customer_type=['기업'])
    def generate(schema, instruction, payload):
        output = payload['draft']
        output['classification'] = {'유형': '잘못된 모델 분류'}
        return output
    report = build_evaluation_report(state, [], generate)
    markdown = render_evaluation_markdown(report)
    assert report.classification['산업 / 세부 산업'] == '로봇 / 휴머노이드'
    assert '잘못된 모델 분류' not in markdown
    assert markdown.index('2. INVESTMENT SNAPSHOT') < markdown.index('기업 분류') < markdown.index('3. BUSINESS IDEA')


def test_business_rubric_separates_missing_positive_and_negative():
    from skala_rag.models.orchestration import EvaluationReport, BusinessScore
    from skala_rag.agents.report import assess_business_report
    from skala_rag.models import Evidence
    keys = ['team','market','technology','traction','moat','scalability']
    def assess(scores, stance='support'):
        evidence = {key: Evidence(evidence_id=key, claim_text='fixture', stance=stance,
            source_type='regulatory', source_grade='A', source_uri='https://example.test/'+key,
            independent=True, value=100) for key in keys}
        report = EvaluationReport(summary='fixture', perspectives=[], analysis_revision=1,
            business_scores=[BusinessScore(criterion=key, score=score, rationale='fixture',
                evidence_ids=[key] if score is not None else []) for key, score in zip(keys, scores)])
        return assess_business_report(report,evidence)
    positive = assess([4,4,4,4,None,None])
    assert positive.business_assessment.signal == 'positive'
    assert positive.business_assessment.coverage_percent == 75
    assert positive.business_assessment.observed_score == 80
    unknown = assess([None,None,4,None,None,None])
    assert unknown.business_assessment.signal == 'undetermined'
    assert unknown.business_assessment.coverage_percent == 25
    negative = assess([2,2,1,1,2,2], 'contradict')
    assert negative.business_assessment.signal == 'concern'
    assert assess([2,2,1,1,2,2]).business_assessment.signal == 'undetermined'
    assert assess([None]*6).business_assessment.observed_score is None


def test_uncited_section_output_is_a_gap_not_a_fact_or_fake_citation():
    from skala_rag.agents.report import normalize_uncited_sections
    payload = {'sections':[{'key':'financials','findings':[{'text':'매출 999억 원','evidence_ids':[]}]}]}
    result = normalize_uncited_sections(payload)
    assert result['sections'][0]['findings'] == []
    assert result['sections'][0]['missing_facts']
    assert '999' not in str(result)
    assert payload['sections'][0]['findings']  # no mutation
