"""기술 분석 에이전트 B.

검색·LLM 연결은 콜백으로 받아 실제 인프라와 분리한다. 이 모듈은 검색 근거를
선별하고, 출처 ID를 붙인 기술 분석과 새 Evidence 목록만 State에 돌려준다.
투자 점수와 판정은 후속 에이전트의 책임이다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date
from typing import Any

from skala_rag.agents.interfaces import AnalysisResult
from skala_rag.models import CompanyProfile, Evidence, MarketCategory, TechAssessment

# 검색 결과에는 논문 적격성·중복 제거용 메타데이터가 섞여 들어온다. 선별 전에는
# 원본 mapping을 유지하고, 그래프로 내보낼 때 공통 Pydantic Evidence로 검증한다.
RawEvidence = dict[str, Any]


# 설계서의 10개 Physical AI 형태마다 중요한 기술 지표가 다르다.
# A가 분류한 형태를 검색 질의에 반영해 일반적인 회사 소개만 검색되는 일을 줄인다.
FORM_METRICS = {
    "고정형 매니퓰레이터": ("가반하중", "반복정밀도", "사이클 타임"),
    "이동형 로봇": ("주행 성공률", "운영시간", "관제 대수"),
    "모바일 매니퓰레이터": ("이동·조작 통합 성공률",),
    "휴머노이드": ("자유도", "가반하중", "보행·균형 검증"),
    "다족보행 로봇": ("지형 통과율", "연속 운용시간"),
    "드론·비행 로봇": ("비행시간", "자율비행 수준", "인증"),
    "해양·수중 로봇": ("운용 수심·시간", "통신 방식"),
    "웨어러블·외골격": ("의료기기 인허가", "임상 결과"),
    "자율주행 차량": ("자율주행 레벨", "누적 주행거리"),
    "스마트 공간·고정형 시스템": ("인식 정확도", "설치 현장 수"),
}
# 지지 근거만으로 요약이 치우치지 않도록 입장별로 따로 검색한다.
# 한 입장의 결과가 부족해도 다른 입장으로 빈 자리를 채우지 않는다.
STANCE_LIMITS = {"support": 3, "contradict": 2, "unknown": 1}
PAPER_TYPES = {"academic", "paper"}
# 논문은 회사/핵심 연구자와의 관계, 현 기술 관련성, 방법·결과 유무를 모두 확인한다.
PAPER_CHECKS = ("paper_company_author", "paper_core_relevant", "paper_has_results")


def _cited(item: RawEvidence) -> str:
    """보고서까지 추적할 수 있도록 주장 뒤에 evidence_id를 남긴다."""
    return f"{item['claim_text']} [{item['evidence_id']}]"


def _assessment(
    evidence: list[RawEvidence], metrics: tuple[str, ...], search_query: str
) -> dict[str, Any]:
    """선별된 근거만으로 TechAssessment를 만든다.

    E등급 미래 목표는 근거 목록에는 남지만 현재 기술의 강점·사양으로 쓰지 않는다.
    확인되지 않은 지표는 추정하지 않고 MissingFact로 기록한다.
    """
    current = [item for item in evidence if item["source_grade"] != "E"]
    supports = [item for item in current if item["stance"] == "support"]
    limits = [item for item in current if item["stance"] == "contradict"]
    assessed = supports + limits
    # support/contradict에 지표명이나 정확한 문구가 있으면 미확인 목록에서 제외한다.
    # 이는 수치 검증 완료를 뜻하지 않으며, unknown의 "미공개" 언급은 제외 근거가 아니다.
    known_metrics = {
        name
        for item in assessed
        for name in (item.get("metric_names") or [])
    }
    known_metrics.update(name for item in assessed for name in (item.get("metrics") or {}))
    # ponytail: 정확한 문구 비교는 동의어를 놓칠 수 있다. 실제 누락 사례가 생기면 별칭을 추가한다.
    known_metrics.update(
        metric for metric in metrics if any(metric in item["claim_text"] for item in assessed)
    )
    # 제품·핵심기술 등은 topic으로 구분한다. 태그가 없는 내용을 제품 사양으로 추측하지 않는다.
    product = [_cited(item) for item in supports if item.get("topic") == "product_spec"]
    core = [_cited(item) for item in supports if item.get("topic") == "core_technology"]
    return {
        "product_summary": " ".join(product) or "확인 불가",
        "core_technology": core or [_cited(item) for item in supports],
        "strengths": [_cited(item) for item in supports],
        "limitations": [_cited(item) for item in limits],
        "patents": [
            _cited(item) for item in assessed if item["source_type"] == "patent"
        ],
        "certifications": [
            _cited(item)
            for item in assessed
            if item.get("topic") == "certification" or item["source_type"] == "certification"
        ],
        "technical_risks": [
            _cited(item) for item in limits if item.get("topic") == "technical_risk"
        ],
        "team": [_cited(item) for item in assessed if item.get("topic") == "team"],
        # 선택된 ID는 E가 다시 근거를 찾을 수 있도록 E등급까지 모두 보존한다.
        "evidence_ids": [item["evidence_id"] for item in evidence],
        "missing_facts": [
            {
                "field": metric,
                "reason": "not_confirmed_in_retrieved_evidence",
                "attempted_queries": [search_query],
                # search 콜백은 실제로 조회한 출처 목록을 주지 않으므로 임의로 채우지 않는다.
                "sources_checked": [],
            }
            for metric in metrics
            if metric not in known_metrics
        ],
    }


def _enrich(
    assessment: dict[str, Any],
    enriched: Mapping[str, Any],
    evidence: list[RawEvidence],
) -> None:
    """선택적 요약 콜백의 내용을 섹션별 적격 근거 ID로 제한한다.

    콜백은 섹션명 -> [{claim_text, evidence_ids}] 형식만 돌려줄 수 있다.
    ID가 존재하더라도 섹션에 맞지 않거나 E등급인 근거는 인용할 수 없다.
    """
    current = [item for item in evidence if item["source_grade"] != "E"]
    supports = [item for item in current if item["stance"] == "support"]
    limits = [item for item in current if item["stance"] == "contradict"]
    assessed = supports + limits
    core = [item for item in supports if item.get("topic") == "core_technology"]
    # 기본 요약을 만든 _assessment와 같은 분류 규칙을 콜백에도 적용한다.
    sections = {
        "product_summary": [item for item in supports if item.get("topic") == "product_spec"],
        "core_technology": core or supports,
        "strengths": supports,
        "limitations": limits,
        "patents": [item for item in assessed if item["source_type"] == "patent"],
        "certifications": [
            item for item in assessed
            if item.get("topic") == "certification" or item["source_type"] == "certification"
        ],
        "technical_risks": [item for item in limits if item.get("topic") == "technical_risk"],
        "team": [item for item in assessed if item.get("topic") == "team"],
    }
    for section, rows in enriched.items():
        if section not in sections or not isinstance(rows, list):
            raise ValueError("summarize may change only cited assessment sections")
        allowed_ids = {item["evidence_id"] for item in sections[section]}
        rendered = []
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != {"claim_text", "evidence_ids"}:
                raise ValueError("summarize must return cited claim records")
            claim = row["claim_text"]
            ids = row["evidence_ids"]
            if (
                not isinstance(claim, str) or not claim.strip()
                or not isinstance(ids, list) or not ids
                or any(not isinstance(eid, str) or eid not in allowed_ids for eid in ids)
            ):
                raise ValueError("summarize returned an uncited or unknown claim")
            rendered.append(f"{claim} [{', '.join(ids)}]")
        assessment[section] = (
            " ".join(rendered) or "확인 불가"
            if section == "product_summary"
            else rendered
        )


def technology_node(
    profile: CompanyProfile,
    category: MarketCategory,
    query: str,
    *,
    search: Callable[..., Iterable[Mapping[str, Any]]],
    summarize: Callable[..., Mapping[str, Any]] | None = None,
) -> AnalysisResult[TechAssessment]:
    """그래프의 TechnologyAnalyzer 계약으로 기술 평가와 근거를 반환한다.

    search 콜백은 company_id, as_of_date, query, stance, limit 키워드 인자를 받는다.
    구현체는 기업·기준일을 필터링하고 OpenSearch BM25(nori)와
    Qwen3-Embedding 벡터 결과를 RRF로 결합해야 한다. 노드도 반환된 근거의
    회사·입장과 명시된 발행일을 재검사한다.

    summarize 콜백은 선택 사항이다. draft=분석 초안과 evidence=tuple을
    받아 섹션별 [{claim_text, evidence_ids}]를 반환한다. _enrich가 출처 ID와
    섹션 적합성을 검사한다. 그래프가 반환값을 tech_analysis·evidence에 넣는다.
    """
    company_id = profile.company_id
    robot_type = profile.physical_ai_type
    as_of_date = profile.as_of_date.isoformat()
    user_query = query
    if not isinstance(company_id, str) or not company_id:
        raise ValueError("company_profile.company_id must be a nonempty string")
    if robot_type not in FORM_METRICS:
        raise ValueError(f"Unsupported physical_ai_type: {robot_type!r}")
    cutoff = profile.as_of_date
    if not isinstance(user_query, str) or not user_query.strip():
        raise ValueError("query must be a nonempty string")
    metrics = FORM_METRICS[robot_type]
    # 사용자의 질문과 A가 정한 시장·형태를 함께 넣되 임베딩 작업 지시문은 질의에만 붙인다.
    search_query = (
        "Physical AI 기업의 기술 사양·실험 결과를 찾는다. "
        f"사용자 질의: {user_query}; 기업: {profile.company_name} ({company_id}); "
        f"시장: {category.industry} / {category.sub_industry}; "
        f"대상: {', '.join(category.target_market)}; 고객: {', '.join(category.customer_type)}; "
        f"분석 범위: {', '.join(category.analysis_scope)}; 형태: {robot_type}; "
        f"핵심 지표: {', '.join(metrics)}; "
        "제품 사양, 논문 방법·실험 조건·기준선·한계, 특허·인증·외부 검증을 확인한다."
    )
    seen_ids: set[str] = set()
    seen_event_claims: set[tuple[str, str]] = set()
    papers: set[str] = set()
    patent_families: set[str] = set()
    evidence: list[RawEvidence] = []
    # 세 입장을 별도로 조회하고, 각 입장 안에서만 정해진 개수까지 선별한다.
    for stance, limit in STANCE_LIMITS.items():
        selected = 0
        for raw in search(
            company_id=company_id, as_of_date=as_of_date,
            query=search_query, stance=stance, limit=limit,
        ):
            item = dict(raw)
            # 백엔드 필터를 믿고 끝내지 않고, 값이 실린 근거는 여기서도 기업·입장을 확인한다.
            # company_id가 없는 근거는 search의 기업 필터 계약을 신뢰해 현재 기업을 부여한다.
            if item.get("company_id", company_id) != company_id or item.get("stance") != stance:
                continue
            # published_at이 있을 때만 기준일 이후 자료를 제외한다. 날짜가 없는 자료의
            # 최신성까지 이 노드가 확인했다고 주장하지 않는다.
            if item.get("published_at") is not None:
                try:
                    published = date.fromisoformat(str(item["published_at"])[:10])
                except (TypeError, ValueError) as exc:
                    raise ValueError("evidence.published_at must begin with YYYY-MM-DD") from exc
                if published > cutoff:
                    continue
            if (
                not isinstance(item.get("evidence_id"), str)
                or not item["evidence_id"]
                or not isinstance(item.get("claim_text"), str)
                or not item["claim_text"].strip()
                or not isinstance(item.get("source_type"), str)
                or not item["source_type"]
                or not isinstance(item.get("source_uri"), str)
                or not item["source_uri"]
                or item.get("source_grade") not in {"A", "B", "C", "D", "E"}
            ):
                raise ValueError("Technical evidence is missing a required source or claim field")
            item.setdefault("company_id", company_id)
            item.setdefault("locator", None)
            item.setdefault("confidence", None)
            evidence_id = item["evidence_id"]
            event_id = item.get("source_event_id")
            # 재배포 기사처럼 같은 이벤트의 동일 주장은 한 번만 쓰되,
            # 같은 이벤트에서 나온 서로 다른 기술 주장까지 버리지는 않는다.
            event_claim = (
                event_id, " ".join(item["claim_text"].split()).casefold()
            ) if event_id else None
            if evidence_id in seen_ids or (event_claim and event_claim in seen_event_claims):
                continue
            source_type = item["source_type"]
            # 논문은 세 적격 조건을 모두 만족하는 고유 문서 최대 3편,
            # 특허는 패밀리 ID로 묶어 최대 5건만 기술 근거로 사용한다.
            if source_type in PAPER_TYPES:
                if not all(item.get(check) is True for check in PAPER_CHECKS):
                    continue
                paper_id = item.get("paper_id") or item["source_uri"]
                if paper_id not in papers and len(papers) >= 3:
                    continue
                papers.add(paper_id)
            elif source_type == "patent":
                family_id = item.get("patent_family_id")
                if not family_id or (family_id not in patent_families and len(patent_families) >= 5):
                    continue
                patent_families.add(family_id)
            seen_ids.add(evidence_id)
            if event_claim:
                seen_event_claims.add(event_claim)
            evidence.append(item)
            selected += 1
            if selected == limit:
                break
    # 검색 단계에서는 점수를 매기지 않는다. 구조화된 요약과 근거를 함께 넘긴다.
    assessment = _assessment(evidence, metrics, search_query)
    if summarize is not None:
        enriched = summarize(draft=assessment, evidence=tuple(evidence))
        if not isinstance(enriched, Mapping):
            raise TypeError("summarize must return a mapping")
        _enrich(assessment, enriched, evidence)
    # 모델 검증과 직렬화 경계를 여기서 통과시킨다. 임의 검색 메타데이터는
    # 공통 Evidence에 선언한 필드만 남겨 그래프와 추후 저장 계층이 같은 계약을 쓴다.
    validated_evidence = [
        Evidence.model_validate({
            name: value for name, value in item.items()
            if name in Evidence.model_fields
        })
        for item in evidence
    ]
    return AnalysisResult(
        assessment=TechAssessment.model_validate(assessment),
        evidence=validated_evidence,
    )
