"""Classify fresh evidence for new or registered companies."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .identity import mentions_name, normalized_name


@dataclass(frozen=True, slots=True)
class DiscoveryHit:
    title: str
    snippet: str
    url: str
    source_grade: str = "D"


class CompanyDiscovery(Protocol):
    def search(self, company_name: str) -> list[DiscoveryHit]: ...


@dataclass(frozen=True, slots=True)
class DiscoveryDecision:
    identity_key: str
    form_key: str | None
    label: str
    status: str
    reason: str
    used_hits: tuple[DiscoveryHit, ...]
    candidate_forms: tuple[str, ...] = ()


class BraveCompanyDiscovery:
    """Optional live search. Search snippets are leads, not verified page text."""

    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, timeout: float = 8.0):
        if not api_key:
            raise ValueError("Brave Search API key is required")
        self._api_key = api_key
        self._timeout = timeout

    @classmethod
    def from_environment(cls) -> BraveCompanyDiscovery | None:
        key = os.getenv("BRAVE_SEARCH_API_KEY")
        return cls(key) if key else None

    def search(self, company_name: str) -> list[DiscoveryHit]:
        params = urlencode({"q": f'"{company_name}" 로봇 제품 기업', "count": 8,
                            "country": "KR", "search_lang": "ko"})
        request = Request(
            f"{self.ENDPOINT}?{params}",
            headers={"Accept": "application/json", "X-Subscription-Token": self._api_key},
        )
        with urlopen(request, timeout=self._timeout) as response:
            payload = json.load(response)
        hits = []
        for result in payload.get("web", {}).get("results", []):
            url = result.get("url", "")
            if urlsplit(url).scheme != "https":
                continue
            hits.append(DiscoveryHit(
                title=result.get("title", ""),
                snippet=result.get("description", ""),
                url=url,
            ))
        return hits


def forms_from_text(text: str) -> set[str]:
    """Collect every form signal, allowing spacing variants in Korean terms."""
    t = text.casefold()
    compact = re.sub(r"\s+", "", t)
    count_nouns = {"robot", "exoskeleton", "drone", "vehicle", "humanoid", "quadruped",
                   "manipulator", "arm", "store", "space", "amr", "agv"}
    def contains(*terms):
        return any(
            re.sub(r"\s+", "", term) in compact if re.search(r"[가-힣]", term)
            else bool(re.search(
                r"(?<![a-z0-9])" + re.escape(term)
                + (r"s?" if term.split()[-1] in count_nouns else "") + r"(?![a-z0-9])", t,
            ))
            for term in terms
        )
    forms: set[str] = set()
    if contains("외골격", "웨어러블 로봇", "보행 보조", "exoskeleton", "wearable robot"):
        forms.add("wearable_exoskeleton")
    if contains("수중 로봇", "무인잠수정", "수상 로봇", "underwater robot", "unmanned surface"):
        forms.add("marine_robot")
    if contains("드론", "무인기", "비행 로봇", "aerial robot", "drone"):
        forms.add("drone")
    if contains("자율주행차", "로보택시", "자율트럭", "autonomous vehicle"):
        forms.add("autonomous_vehicle")
    if contains("이족보행", "두 발로 걷", "bipedal", "humanoid", "휴머노이드"):
        forms.add("humanoid")
    if contains("사족보행", "4족", "다족보행", "quadruped", "four-legged"):
        forms.add("legged_robot")
    if contains("배송 로봇", "배달 로봇", "순찰 로봇", "자율이동로봇", "amr", "agv", "mobile robot"):
        forms.add("mobile_robot")
    if contains("협동로봇", "로봇팔", "fixed manipulator", "robotic arm", "robot arm"):
        forms.add("fixed_manipulator")
    if contains("ai 카메라", "스마트 공간", "영상관제", "automated store", "smart space"):
        forms.add("smart_space")
    if contains("모바일 매니퓰레이터", "mobile manipulator"):
        forms.add("mobile_manipulator")
    # Resolve a combined wheel/arm mechanism only when described in one clause.
    # Keep other product/form signals; never select the first matched category.
    for clause in re.split(r"[.!?;\n]", t):
        c = re.sub(r"\s+", "", clause)
        wheel = any(term in c for term in ("바퀴", "이동플랫폼", "wheeled")) or bool(re.search(r"\bamr\b", clause))
        arm = any(term in c for term in ("로봇팔", "양팔", "조작팔", "robotarm", "manipulator"))
        if wheel and arm:
            forms.add("mobile_manipulator")
    return forms


def classify_discovered(name: str, hits: list[DiscoveryHit], aliases: tuple[str, ...] = ()) -> DiscoveryDecision:
    """Propose forms; separate domains alone do not prove source independence."""

    identity = hashlib.sha256(normalized_name(name).encode("utf-8")).hexdigest()[:12]
    matched = []
    for hit in hits:
        if not hit.url.startswith(("https://", "http://")):
            continue
        text = f"{hit.title} {hit.snippet}"
        if not any(mentions_name(text, alias) for alias in (name, *aliases)):
            continue
        matched.append(hit)
    if not matched:
        return DiscoveryDecision(identity, None, "분류 검토 필요", "insufficient_evidence",
                                 "기업명과 일치하는 출처 미확보", ())

    by_form: dict[str, list[DiscoveryHit]] = {}
    for hit in matched:
        for key in forms_from_text(f"{hit.title} {hit.snippet}"):
            by_form.setdefault(key, []).append(hit)
    if not by_form:
        return DiscoveryDecision(identity, None, "분류 검토 필요", "insufficient_evidence",
                                 "기업은 언급되지만 제품의 물리적 형태를 확인할 수 없음",
                                 tuple(matched))
    if len(by_form) != 1:
        return DiscoveryDecision(identity, None, "분류 검토 필요", "conflicting_forms",
                                 "한 문서 또는 출처 사이에 복수 형태 신호 존재; 제품별 분리 확인 필요",
                                 tuple(matched), tuple(sorted(by_form)))

    form_key, support = next(iter(by_form.items()))
    domains = {(urlsplit(hit.url).hostname or "").removeprefix("www.") for hit in support}
    official = any(hit.source_grade == "C" for hit in support)
    if not official and len(domains) < 2:
        return DiscoveryDecision(identity, None, "분류 검토 필요", "insufficient_evidence",
                                 "검색 결과 한 출처만으로 형태 확정 불가", tuple(matched), (form_key,))
    return DiscoveryDecision(identity, form_key, "", "proposed_needs_review",
                             "제품 형태를 가리키는 출처 확인; 원문·동일 법인 수동 검토 필요",
                             tuple(support), (form_key,))
