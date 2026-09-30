"""E 에이전트: 이미 수집된 근거로 LLM 점수를 검증하고 투자 의견을 결정한다."""

from __future__ import annotations

from collections.abc import Callable
from math import isfinite
from typing import Any

from skala_rag.agents.interfaces import DecisionResult
from skala_rag.models import (
    Evidence, FinancialAssessment, InvestmentDecision, MarketAssessment,
    ScoreDetail, TechAssessment,
)


# 설계서의 여섯 평가 항목. 가중치 합은 100점이다.
CRITERIA = {
    "team": (15, "창업팀 역량·시장 적합성"),
    "market": (15, "시장 매력도"),
    "technology": (25, "제품·기술 경쟁력"),
    "traction": (20, "시장 검증·사업 성과"),
    "moat": (10, "지속 가능한 경쟁우위"),
    "scalability": (15, "확장성·제품당 수익성"),
}
MISSING = {"not_disclosed", "not_found"}
MISSING_STATUSES = MISSING | {"not_applicable", "confirmed_absent", "unknown"}


def _quantitative(evidence: dict[str, Any]) -> bool:
    """정량 근거는 별도 표시가 아니라 실제 숫자(value 또는 metrics)로 확인한다."""
    value = evidence.get("value")
    metrics = evidence.get("metrics")
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        or isinstance(metrics, dict)
        and any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in metrics.values())
    )


def _score_cap(evidence: list[dict[str, Any]]) -> int:
    """인용한 근거만으로 허용 가능한 최고 점수를 계산한다.

    같은 발표를 재인용한 자료는 source_event_id로 한 출처로 묶는다.
    독립적인 A/B 정량 근거는 5점, 회사 정량 근거와 별도 외부 확인은 4점,
    A~C 근거는 최대 3점, D 근거만 있으면 최대 2점, 지지 근거가 없으면 1점이다.
    같은 상한 안에서 2점과 3점을 가르는 내용 판단은 LLM 채점 함수가 맡는다.
    """
    events: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        if item.get("stance") == "support":
            events.setdefault(item.get("source_event_id") or item["evidence_id"], []).append(item)
    sources = [
        (
            event_id,
            min((item["source_grade"] for item in items), key="ABCD".index),
            all(item.get("independent") is True for item in items),
            any(_quantitative(item) for item in items),
        )
        for event_id, items in events.items()
    ]
    if any(
        grade in {"A", "B"} and independent and quantitative
        for _, grade, independent, quantitative in sources
    ):
        return 5
    if any(
        quantitative and not independent
        and any(
            external_event != company_event
            and external_grade in {"A", "B"}
            and external_independent
            for external_event, external_grade, external_independent, _ in sources
        )
        for company_event, _, independent, quantitative in sources
    ):
        return 4
    if any(grade in {"A", "B", "C"} for _, grade, _, _ in sources):
        return 3
    return 2 if sources else 1


def decision_node(
    tech: TechAssessment,
    market: MarketAssessment,
    financial: FinancialAssessment,
    evidence: list[Evidence],
    *,
    score: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, dict[str, Any]]],
) -> DecisionResult:
    """그래프의 DecisionMaker 계약으로 검증된 판정과 점수를 반환한다.

    ``score(view, evidence)``는 현재 기업의 기술·시장·재무 분석과 A~D 등급
    근거만 받는다. 여섯 항목 각각에 1~5 정수 ``score``, ``rationale``
    (기존 호출자는 ``reason``도 가능), ``evidence_ids``, 0~1 ``confidence``
    또는 None을 반환해야 한다. 근거를 찾지 못했다면 ``missing_status``도 적는다.
    그래프 모델의 score는 0~100점, weight는 0~1 비율이므로 검증한 1~5점과
    정수 가중치를 반환 직전에 변환한다. 재무제표 미확보 시 채점하지 않는다.
    """
    # 그래프가 전달한 Pydantic 모델만 받는다. 내부 판정 규칙에는 변경 가능한
    # 사본을 넘겨 LLM 콜백이 그래프 State 자체를 수정하지 못하도록 한다.
    state = {
        "tech_analysis": tech.model_dump(),
        "market_analysis": market.model_dump(),
        "financial_analysis": financial.model_dump(),
        "evidence": [item.model_dump() for item in evidence],
    }
    financial_data = state["financial_analysis"]
    if financial_data["status"] not in {"available", "unavailable"}:
        raise ValueError("financial_analysis.status must be available or unavailable")

    scores: dict[str, dict[str, Any]] = {}
    total: float | None = None
    confidence: float | None = None
    investment_reasons: list[str] = []
    counter_arguments: list[str] = []
    red_flags: list[str] = []
    conditions: list[str] = []
    decision_evidence_ids: list[str] = []
    # 재무제표가 없으면 점수를 추정하지 않고 첫 번째 판정 규칙을 즉시 적용한다.
    if financial_data["status"] == "unavailable":
        verdict = "DUE_DILIGENCE"
        conditions = ["최근 사업연도 총자산과 당기순손익 또는 매출 확인"]
        red_flags = ["재무제표 미확보"]
    else:
        # 그래프 State에는 여러 노드의 근거가 누적되므로 분석 결과가 인용한 ID만
        # 고른다. company_id가 있으면 서로 다른 기업 자료의 혼입도 확인한다.
        analyses = (state["tech_analysis"], state["market_analysis"], financial_data)
        analysis_ids: list[str] = []
        for analysis in analyses:
            ids = analysis["evidence_ids"]
            if not isinstance(ids, list) or any(not isinstance(eid, str) for eid in ids):
                raise ValueError("assessment evidence_ids must be lists of strings")
            analysis_ids.extend(ids)
        allowed_ids = set(analysis_ids)
        by_id: dict[str, dict[str, Any]] = {}
        for item in state.get("evidence", []):
            evidence_id = item["evidence_id"]
            if evidence_id not in allowed_ids:
                continue
            if evidence_id in by_id and by_id[evidence_id] != item:
                raise ValueError(f"conflicting evidence_id: {evidence_id}")
            by_id[evidence_id] = item
        if allowed_ids - by_id.keys():
            raise ValueError(f"assessment references missing evidence: {sorted(allowed_ids - by_id.keys())}")
        company_ids = {item["company_id"] for item in by_id.values() if item.get("company_id")}
        if len(company_ids) > 1:
            raise ValueError("assessments cite evidence from different companies")
        # E 등급은 미래 목표·예정 사양이라 현재 상태 채점과 인용에서 제외한다.
        current_evidence = [item for item in by_id.values() if item["source_grade"] != "E"]
        current_by_id = {item["evidence_id"]: item for item in current_evidence}
        scorer_state = {
            "tech_analysis": state["tech_analysis"],
            "market_analysis": state["market_analysis"],
            "financial_analysis": financial_data,
            "evidence": current_evidence,
        }
        proposed = score(scorer_state, current_evidence)
        if not isinstance(proposed, dict) or set(proposed) != set(CRITERIA):
            raise ValueError(f"score must return exactly: {', '.join(CRITERIA)}")

        # 항목마다 LLM 점수의 형식, 현재 기업 근거 ID, 근거 수준별 점수 상한을 확인한다.
        missing: list[str] = []
        passed: list[str] = []
        total = 0.0
        for key, (weight, _) in CRITERIA.items():
            item = proposed[key]
            if not isinstance(item, dict):
                raise ValueError(f"{key}: expected a dict")
            points = item.get("score")
            ids = item.get("evidence_ids")
            rationale = item.get("rationale", item.get("reason"))
            missing_status = item.get("missing_status")
            item_confidence = item.get("confidence")
            if type(points) is not int or not 1 <= points <= 5:
                raise ValueError(f"{key}: score must be an integer from 1 to 5")
            if not isinstance(ids, list) or any(not isinstance(eid, str) for eid in ids):
                raise ValueError(f"{key}: evidence_ids must be a list of strings")
            if not isinstance(rationale, str) or not rationale.strip():
                raise ValueError(f"{key}: rationale is required")
            if missing_status is not None and missing_status not in MISSING_STATUSES:
                raise ValueError(f"{key}: invalid missing_status")
            if item_confidence is not None:
                if (isinstance(item_confidence, bool) or not isinstance(item_confidence, (int, float))
                        or not isfinite(item_confidence) or not 0 <= item_confidence <= 1):
                    raise ValueError(f"{key}: confidence must be between 0 and 1 or None")
                item_confidence = float(item_confidence)
            ids = list(dict.fromkeys(ids))
            unknown = set(ids) - current_by_id.keys()
            if unknown:
                raise ValueError(f"{key}: unknown, cross-company, or grade E evidence: {sorted(unknown)}")
            cited = [current_by_id[eid] for eid in ids]
            cap = _score_cap(cited)
            if points > cap:
                raise ValueError(f"{key}: score {points} exceeds evidence-supported maximum {cap}")
            substantive = any(evidence["stance"] in {"support", "contradict"} for evidence in cited)
            if not substantive and missing_status is None:
                raise ValueError(f"{key}: missing_status is required without supporting evidence")

            # 원점수(1~5)를 항목 가중치로 환산한다. 제한 근거만 있는 1점은
            # '근거 없음'이 아니므로 not_found/not_disclosed 개수에 넣지 않는다.
            total += points / 5 * weight
            scores[key] = {
                "dimension": key,
                "score": points,
                "weight": weight,
                "confidence": item_confidence,
                "rationale": rationale.strip(),
                "evidence_ids": ids,
            }
            if missing_status is not None:
                scores[key]["missing_status"] = missing_status
            if points >= 3:
                passed.append(key)
            if not substantive and missing_status in MISSING:
                missing.append(key)
            decision_evidence_ids.extend(ids)
        decision_evidence_ids = list(dict.fromkeys(decision_evidence_ids))
        # 여섯 항목이 모두 신뢰도를 제시했을 때만 가중평균을 낸다. 빈 값을 추정하지 않는다.
        if all(detail["confidence"] is not None for detail in scores.values()):
            confidence = sum(detail["confidence"] * detail["weight"] for detail in scores.values()) / 100

        def cited_reason(key: str) -> str:
            # 보고서 노드는 scores를 읽지 않으므로 판정 사유에도 근거 ID를 붙인다.
            ids = scores[key]["evidence_ids"]
            citation = f" [{', '.join(ids)}]" if ids else ""
            return f"{CRITERIA[key][1]}: {scores[key]['rationale']}{citation}"

        # 설계서 순서: 근거 없음 3개 이상 → 전 항목 통과·75점 이상 →
        # 기술 포함 5개 이상 통과 → 그 외 제외. 재무 부재는 위에서 먼저 처리했다.
        if len(missing) >= 3:
            verdict = "DUE_DILIGENCE"
            conditions = [f"{CRITERIA[key][1]} 근거 확인" for key in missing[:3]]
            red_flags = [cited_reason(key) for key in missing[:5]]
        elif len(passed) == 6 and total >= 75:
            verdict = "INVEST"
        elif len(passed) >= 5 and "technology" in passed:
            verdict = "CONDITIONAL"
            failed = [key for key in CRITERIA if key not in passed]
            if failed:
                conditions = [f"보완: {cited_reason(key)}" for key in failed[:3]]
                red_flags = [cited_reason(key) for key in failed[:5]]
            else:
                lowest = min(CRITERIA, key=lambda key: (scores[key]["score"], -CRITERIA[key][0]))
                conditions = [f"{cited_reason(lowest)} 근거 보강 후 총점 75점 이상 재평가"]
                red_flags = [f"투자 기준 75점 미달: {cited_reason(lowest)}"]
        else:
            verdict = "REJECT"
            failed = [key for key in CRITERIA if key not in passed]
            red_flags = [cited_reason(key) for key in failed[:5]]

        if verdict in {"INVEST", "CONDITIONAL"}:
            top = sorted(passed, key=lambda key: scores[key]["score"] / 5 * CRITERIA[key][0], reverse=True)[:3]
            investment_reasons = [cited_reason(key) for key in top]
        seen_events: set[str] = set()
        # 반대 논거도 현재 기업의 실제 제한 근거에서만 만들고 인용 ID를 함께 남긴다.
        for item in sorted(current_evidence, key=lambda evidence: evidence["evidence_id"]):
            if item["stance"] != "contradict" or not item["claim_text"]:
                continue
            event = item.get("source_event_id") or item["evidence_id"]
            if event in seen_events:
                continue
            seen_events.add(event)
            counter_arguments.append(f"{item['claim_text']} [{item['evidence_id']}]")
            decision_evidence_ids.append(item["evidence_id"])
            if len(counter_arguments) == 2:
                break
        decision_evidence_ids = list(dict.fromkeys(decision_evidence_ids))
        # 세부 위험 문장에 대응하는 인용이 없으면 사실을 만들어 쓰지 않고 범주만 적는다.
        for label, analysis, field in (
            ("기술 위험", state["tech_analysis"], "technical_risks"),
            ("시장 위험", state["market_analysis"], "market_risks"),
            ("재무 위험", financial_data, "financial_risks"),
        ):
            if analysis.get(field):
                red_flags.append(label)
        red_flags = list(dict.fromkeys(red_flags))[:5]

    # 그래프·보고서가 쓰는 한국어 판정 값으로 변환한다.
    graph_verdict = {
        "INVEST": "투자", "CONDITIONAL": "조건부 투자",
        "DUE_DILIGENCE": "추가 실사", "REJECT": "투자 제외",
    }[verdict]
    decision = InvestmentDecision(
        decision=graph_verdict,
        total_score=total,
        confidence=confidence,
        investment_reasons=investment_reasons,
        counter_arguments=counter_arguments,
        red_flags=red_flags,
        conditions=conditions,
        evidence_ids=decision_evidence_ids,
    )
    # 내부 원점수(1~5)를 그래프 모델의 0~100점으로, 가중치(합 100)를
    # 0~1 비율로 바꾼다. 총점은 앞에서 계산한 100점 만점을 그대로 사용한다.
    graph_scores = {
        key: ScoreDetail(
            dimension=key,
            score=detail["score"] * 20,
            weight=detail["weight"] / 100,
            confidence=detail["confidence"],
            rationale=detail["rationale"],
            evidence_ids=detail["evidence_ids"],
            missing_status=detail.get("missing_status"),
        )
        for key, detail in scores.items()
    }
    return DecisionResult(decision=decision, scores=graph_scores)
