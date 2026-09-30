"""실제 LangGraph가 B·E 구현을 호출하고 JSON 결과를 만드는지 확인한다."""

import json
from datetime import date
from functools import partial

import pytest

from skala_rag.agents import AnalysisResult, ClassificationResult, InvestmentAgents
from skala_rag.agents.decision import CRITERIA, decision_node
from skala_rag.agents.tech import load_faiss_search, technology_node
from skala_rag.graph import build_investment_graph, to_storage_payload
from skala_rag.models import (
    CompanyProfile, Evidence, FinancialAssessment, InvestmentReport,
    MarketAssessment, MarketCategory,
)


COMPANY_ID = "sample"


def _evidence(evidence_id: str, **changes: object) -> Evidence:
    """시장·재무 노드가 이미 추출했다고 가정한 주장 한 건."""
    fields = {
        "evidence_id": evidence_id,
        "claim_text": f"{evidence_id} 검증 자료",
        "stance": "support",
        "source_type": "regulatory",
        "source_grade": "A",
        "source_uri": f"https://example.test/{evidence_id}",
        "confidence": 0.9,
        "company_id": COMPANY_ID,
        "independent": True,
        "value": 1.0,
    }
    fields.update(changes)
    return Evidence.model_validate(fields)


def _search(**kwargs: object) -> list[dict[str, object]]:
    """FAISS 인덱스 없이도 B·E 연결을 시험하는 고정 검색기."""
    assert kwargs["company_id"] == COMPANY_ID
    assert kwargs["as_of_date"] == "2026-09-30"
    assert "물류 로봇" in kwargs["query"]
    technical = {
        **_evidence("TECH-1", claim_text="실물 주행 성공률 90%", topic="product_spec").model_dump(),
        "paper_company_author": True,
        "paper_core_relevant": True,
        "paper_has_results": True,
        "source_type": "academic",
    }
    team = _evidence("TEAM-1", claim_text="핵심 연구진 논문 2편", topic="team").model_dump()
    later = {**technical, "evidence_id": "LATER", "published_at": "2026-10-01"}
    limit = _evidence(
        "LIMIT-1", claim_text="야간 주행 미검증", stance="contradict",
        topic="technical_risk",
    ).model_dump()
    future = _evidence(
        "FUTURE", claim_text="내년 자율주행 목표", source_grade="E", stance="unknown",
    ).model_dump()
    return {
        "support": [technical, team, later],
        "contradict": [limit],
        "unknown": [future],
    }[kwargs["stance"]]


def _judge_context(*, question: str, response: str, context: str) -> bool:
    """정답 문서 없이 각 검색 청크의 유용성을 판단하는 LLM 대역."""
    assert "야외 배송" in question
    assert "내년 자율주행 목표" not in response
    return "핵심 연구진" in context or "야간 주행" in context


def _judge_claims(*, question: str, contexts: tuple[str, ...], response: str) -> list[dict]:
    """답변을 원자적 주장으로 나눠 근거성 여부를 반환하는 LLM 대역."""
    assert len(contexts) == 3  # 현재 기술의 TECH-1, TEAM-1, LIMIT-1만 사용한다.
    assert "내년 자율주행 목표" not in contexts
    assert "실물 주행 성공률 90%" in response
    assert "상용화 완료" in response
    return [
        {"claim_text": "실물 주행 성공률 90%", "supported": True},
        {"claim_text": "상용화 완료", "supported": False},
    ]


def _summarize(*, draft: dict, evidence: tuple) -> dict:
    """출처 ID는 맞지만 사실과 다른 문장을 넣어 Faithfulness를 시험한다."""
    return {"product_summary": [
        {"claim_text": "실물 주행 성공률 90%", "evidence_ids": ["TECH-1"]},
        {"claim_text": "상용화 완료", "evidence_ids": ["TECH-1"]},
    ]}


def _score(view: dict, evidence: list[dict]) -> dict:
    """LLM의 1~5점 제안을 흉내 낸다. E가 근거·가중치를 검증한다."""
    assert set(view) == {"tech_analysis", "market_analysis", "financial_analysis", "evidence"}
    assert view["tech_analysis"]["team"]
    assert view["financial_analysis"]["status"] == "available"
    assert all(item["company_id"] == COMPANY_ID and item["source_grade"] != "E" for item in evidence)
    cited = {
        "team": "TEAM-1", "market": "market", "technology": "TECH-1",
        "traction": "traction", "moat": "moat", "scalability": "scalability",
    }
    return {
        key: {"score": points, "evidence_ids": [cited[key]],
              "rationale": "검증 근거", "confidence": 0.8}
        for key, points in zip(CRITERIA, (4, 4, 4, 4, 3, 4))
    }


def _profile() -> CompanyProfile:
    return CompanyProfile(
        company_id=COMPANY_ID, company_name="샘플 로보틱스",
        physical_ai_type="이동형 로봇", stage="seed", as_of_date=date(2026, 9, 30),
    )


def _category() -> MarketCategory:
    return MarketCategory(
        industry="로봇", sub_industry="물류 로봇", target_market=["야외 배송"],
        customer_type=["기업"], analysis_scope=["배송 실증"],
    )


def test_b_e_run_inside_graph_and_prepare_storage_payload() -> None:
    """B의 근거를 E가 읽고, 그래프 결과를 DB 호출 없이 JSON으로 만든다."""
    def classify(query: str, as_of_date: str) -> ClassificationResult:
        assert as_of_date == "2026-09-30"
        return ClassificationResult(_profile(), _category())

    def market(profile, category, query):
        ids = ["market", "traction", "moat"]
        return AnalysisResult(
            MarketAssessment(evidence_ids=ids), [_evidence(key) for key in ids]
        )

    def finance(profile, tech, market_result):
        return AnalysisResult(
            FinancialAssessment(status="available", evidence_ids=["scalability"]),
            [_evidence("scalability")],
        )

    def report(profile, tech, market_result, financial, decision, evidence):
        return InvestmentReport(
            summary="요약", technology=tech.product_summary,
            market_competition="시장", financials="재무", risks="위험",
            decision=decision.decision,
            references=[item.evidence_id for item in evidence],
        )

    agents = InvestmentAgents(
        classify_market=classify,
        analyze_technology=partial(
            technology_node, search=_search, summarize=_summarize,
            judge_context=_judge_context, judge_claims=_judge_claims,
        ),
        analyze_market=market,
        analyze_financials=finance,
        make_decision=partial(decision_node, score=_score),
        write_report=report,
    )
    graph = build_investment_graph(agents)
    result = graph.invoke({"query": "야외 배송 기술을 평가해줘", "as_of_date": "2026-09-30"})

    assert result["tech_analysis"].team == ["핵심 연구진 논문 2편 [TEAM-1]"]
    assert {fact.field for fact in result["tech_analysis"].missing_facts} == {"운영시간", "관제 대수"}
    rag = result["tech_analysis"].rag_evaluation
    assert rag is not None
    assert rag.context_precision == 0.5
    assert rag.context_precision_by_stance == {
        "support": 0.5, "contradict": 1.0, "unknown": 0.0,
    }
    assert rag.faithfulness == 0.5
    assert rag.judged_contexts == 5 and rag.judged_claims == 2
    assert result["decision"].decision == "투자"
    assert result["decision"].total_score == 78
    assert result["scores"]["technology"].score == 80
    assert result["scores"]["technology"].weight == 0.25
    assert result["report"].decision == "투자"
    assert "LATER" not in {item.evidence_id for item in result["evidence"]}

    payload = to_storage_payload(result)
    assert payload["company_profile"]["as_of_date"] == "2026-09-30"
    assert payload["decision"]["decision"] == "투자"
    assert payload["scores"]["technology"]["evidence_ids"] == ["TECH-1"]
    assert payload["tech_analysis"]["rag_evaluation"]["faithfulness"] == 0.5
    assert payload["evidence"][0]["company_id"] == COMPANY_ID
    json.dumps(payload, ensure_ascii=False)


def test_decision_rejects_future_evidence_and_skips_missing_financials() -> None:
    """미래 계획 인용을 거부하고, 재무자료가 없으면 LLM 채점을 호출하지 않는다."""
    profile, category = _profile(), _category()
    tech_result = technology_node(profile, category, "기술 평가", search=_search)
    market_result = MarketAssessment(evidence_ids=["market", "traction", "moat"])
    financial = FinancialAssessment(status="available", evidence_ids=["scalability"])
    all_evidence = tech_result.evidence + [
        _evidence(key) for key in ("market", "traction", "moat", "scalability")
    ]

    def invalid_score(view, current):
        proposed = _score(view, current)
        proposed["technology"]["evidence_ids"] = ["FUTURE"]
        proposed["technology"]["score"] = 5
        return proposed

    with pytest.raises(ValueError, match="grade E evidence"):
        decision_node(
            tech_result.assessment, market_result, financial, all_evidence,
            score=invalid_score,
        )

    # 출처가 회사 발표(C등급) 한 건뿐이면 정량 값이 있어도 5점을 허용하지 않는다.
    weak = _evidence("WEAK", source_grade="C", independent=False)
    weak_tech = tech_result.assessment.model_copy(
        update={"evidence_ids": tech_result.assessment.evidence_ids + ["WEAK"]}
    )

    def unsupported_score(view, current):
        proposed = _score(view, current)
        proposed["technology"]["evidence_ids"] = ["WEAK"]
        proposed["technology"]["score"] = 5
        return proposed

    with pytest.raises(ValueError, match="exceeds evidence-supported maximum"):
        decision_node(
            weak_tech, market_result, financial, all_evidence + [weak],
            score=unsupported_score,
        )

    skipped = decision_node(
        tech_result.assessment, market_result, FinancialAssessment(), all_evidence,
        score=lambda *_: (_ for _ in ()).throw(AssertionError("scorer called")),
    )
    assert skipped.decision.decision == "추가 실사"
    assert skipped.decision.total_score is None
    assert skipped.scores == {}


def test_technology_reads_prebuilt_faiss_index(tmp_path) -> None:
    """FAISS ID와 JSONL 메타데이터를 연결해 회사·시점·입장을 필터링한다."""
    import faiss
    import numpy as np

    index = faiss.IndexFlatL2(2)
    index.add(np.asarray(
        [[0.0, 0.0], [0.1, 0.0], [0.2, 0.0], [0.3, 0.0], [0.4, 0.0]],
        dtype="float32",
    ))
    index_path = tmp_path / "evidence.faiss"
    metadata_path = tmp_path / "evidence.jsonl"
    faiss.write_index(index, str(index_path))
    rows = [
        _evidence("TECH-1", claim_text="주행 성공률 90%", topic="product_spec"),
        _evidence("OTHER", company_id="another-company"),
        _evidence("LATER", published_at=date(2026, 10, 1)),
        _evidence("LIMIT-1", stance="contradict", topic="technical_risk"),
        _evidence("TEAM-1", topic="team"),
    ]
    metadata_path.write_text(
        "\n".join(json.dumps({"faiss_id": faiss_id, **row.model_dump(mode="json")})
                  for faiss_id, row in enumerate(rows)) + "\n",
        encoding="utf-8",
    )
    search = load_faiss_search(index_path, metadata_path, lambda _: [0.0, 0.0])
    result = technology_node(_profile(), _category(), "야외 배송 기술 평가", search=search)

    assert result.assessment.evidence_ids == ["TECH-1", "TEAM-1", "LIMIT-1"]
    assert result.assessment.patents == []
