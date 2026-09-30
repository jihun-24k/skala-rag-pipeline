"""Agent A: classify incoming company evidence or look up a registered profile."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from typing import Any, Mapping

from skala_rag.agents.interfaces import ClassificationResult
from skala_rag.models import CompanyProfile, MarketCategory

from .catalog import CompanyCatalog, JsonCompanyCatalog
from .taxonomy import FORMS
from .discovery import CompanyDiscovery, DiscoveryHit, BraveCompanyDiscovery, classify_discovered
from .identity import mentions_name, normalized_name


class CompanyNotFoundError(ValueError):
    """The requested company has no unambiguous record in the master."""


def _mentioned(query: str, alias: str) -> bool:
    """Avoid substring matches such as ROBROS inside an unrelated identifier."""

    return mentions_name(query, alias)


class MarketClassificationAgent:
    """Rule-based evidence classification and master lookup; no investment scoring."""

    def __init__(
        self,
        catalog: CompanyCatalog | None = None,
        discovery: CompanyDiscovery | None = None,
    ):
        self.catalog = catalog or JsonCompanyCatalog()
        self.discovery = discovery or BraveCompanyDiscovery.from_environment()

    def __call__(self, query: str, as_of_date: str) -> ClassificationResult:
        matches = [
            company for company in self.catalog.list_companies()
            if _mentioned(query, company["id"])
            or any(_mentioned(query, alias) for alias in company.get("aliases", []))
        ]
        if not matches:
            name = re.sub(
                r"(?:을|를|에 대해|의)?\s*(?:분석|분류|조사|평가|알려).*$",
                "", query.strip(), flags=re.IGNORECASE,
            ).strip()
            return self._discover(name, as_of_date)
        if len(matches) != 1:
            raise CompanyNotFoundError(
                f"여러 등록 기업이 일치함: {query!r}; candidate_companies를 지정하세요"
            )
        return self._classify(matches[0], as_of_date)

    def classify_company(
        self, company: Mapping[str, Any], *, as_of_date: str,
    ) -> ClassificationResult:
        """Accept one structured company object without a natural-language query."""
        if not isinstance(company, Mapping):
            raise TypeError("company must be a mapping containing company_name or company_id")
        return self.classify_state({
            "candidate_companies": [company], "current_index": 0,
            "as_of_date": as_of_date,
        })

    def classify_state(self, state: Mapping[str, Any]) -> ClassificationResult:
        """PDF section 2.1 contract: candidate_companies + current_index."""

        candidates = state.get("candidate_companies")
        if candidates is None:
            if not isinstance(state.get("query"), str) or not state["query"].strip():
                raise ValueError("Provide candidate_companies or a nonempty query")
            return self(state["query"], state["as_of_date"])
        index = state.get("current_index", 0)
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(candidates):
            raise IndexError("current_index must select a candidate_companies entry")
        candidate = candidates[index]
        if isinstance(candidate, str):
            company = self.catalog.get_company(candidate)
            if company is None:
                matches = self._named_companies(candidate)
                if len(matches) == 1:
                    company = matches[0]
                elif not matches:
                    return self._discover(candidate, state["as_of_date"])
                else:
                    raise CompanyNotFoundError(f"Ambiguous company name: {candidate!r}")
        elif isinstance(candidate, Mapping):
            identity = candidate.get("company_id") or candidate.get("id")
            if isinstance(identity, str):
                company = self.catalog.get_company(identity)
            else:
                company = None
            if company is None:
                name = candidate.get("company_name") or candidate.get("name") or identity
                if not isinstance(name, str) or not name.strip():
                    raise CompanyNotFoundError("Candidate must include company name or ID")
                matches = self._named_companies(name)
                if len(matches) > 1:
                    raise CompanyNotFoundError(f"Ambiguous company name: {name!r}")
                if matches:
                    company = matches[0]
                else:
                    return self._discover(name.strip(), state["as_of_date"], candidate)
            if "evidence" in candidate:
                # Preserve known identity, but classify from the new evidence only.
                # Even an empty evidence list must not silently reuse an old form.
                aliases = candidate.get("aliases", [])
                if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
                    raise ValueError("aliases must be a list of company names")
                fresh = dict(candidate)
                fresh["aliases"] = list(dict.fromkeys([
                    company["id"], *company.get("aliases", []), *aliases,
                ]))
                result = self._discover(company["canonical_name"], state["as_of_date"], fresh)
                return replace(
                    result,
                    company_profile=result.company_profile.model_copy(update={"company_id": company["id"]}),
                    current_company={**result.current_company, "company_id": company["id"]},
                )
        else:
            raise TypeError("Candidate must be a company ID or mapping")
        if company is None:
            raise CompanyNotFoundError(f"Company is not registered: {candidate!r}")
        return self._classify(company, state["as_of_date"])

    def _named_companies(self, name: str) -> list[dict[str, Any]]:
        key = normalized_name(name)
        return [item for item in self.catalog.list_companies()
                if key and key in {normalized_name(alias) for alias in
                                   [item["id"], item["canonical_name"], *item.get("aliases", [])]}]

    def _discover(
        self,
        name: str,
        as_of_date: str,
        candidate: Mapping[str, Any] | None = None,
    ) -> ClassificationResult:
        """Classify an arbitrary company from supplied facts and/or a search provider."""

        requested = date.fromisoformat(as_of_date)
        if not name:
            raise CompanyNotFoundError("A company name is required for discovery")
        candidate = candidate or {}
        supplied = candidate.get("evidence", [])
        hits: list[DiscoveryHit] = []
        if isinstance(supplied, list):
            for item in supplied:
                if not isinstance(item, Mapping):
                    continue
                url = item.get("url") or item.get("source_url")
                if isinstance(url, str) and url.startswith(("https://", "http://")):
                    hits.append(DiscoveryHit(
                        title=str(item.get("title", "")),
                        snippet=str(item.get("text") or item.get("snippet") or ""),
                        url=url,
                        source_grade="C" if item.get("official") is True else "D",
                    ))
        discovery_error = None
        if "evidence" not in candidate and self.discovery is not None:
            try:
                hits = self.discovery.search(name)
            except (OSError, ValueError) as exc:
                discovery_error = type(exc).__name__
        aliases = candidate.get("aliases", [])
        if not isinstance(aliases, list) or not all(isinstance(alias, str) for alias in aliases):
            raise ValueError("aliases must be a list of company names")
        decision = classify_discovered(name, hits, tuple(aliases))
        if discovery_error:
            decision = replace(
                decision,
                status="discovery_unavailable",
                reason=f"검색 서비스 오류({discovery_error}); 원문 자료를 전달하거나 재시도 필요",
            )
        form = FORMS.get(decision.form_key)
        label = form.label if form else decision.label
        company_id = "discovered:" + decision.identity_key
        urls = [hit.url for hit in decision.used_hits]
        profile = CompanyProfile(
            company_id=company_id,
            company_name=name,
            physical_ai_type=label,
            stage="미확인",
            as_of_date=requested,
            listing_status=None,
            classification_status=decision.status,
            source_urls=urls,
        )
        category = MarketCategory(
            industry="Physical AI / Robotics" if form else "분류 미확정",
            sub_industry=label,
            secondary_forms=[FORMS[key].label for key in decision.candidate_forms
                             if key != decision.form_key],
            priority_metrics=list(form.priority_metrics) if form else [],
            review_required=True,
        )
        current_company: dict[str, object] = {
            "company_id": company_id,
            "canonical_name": name,
            "primary_form": decision.form_key,
            "classification_status": decision.status,
            "classification_reason": decision.reason,
            "candidate_forms": list(decision.candidate_forms),
            "aliases": aliases,
            "source_urls": urls,
            "discovery_sources": [{
                "title": hit.title, "snippet": hit.snippet,
                "url": hit.url, "source_grade": hit.source_grade,
            } for hit in decision.used_hits],
            "listing_status": None,
            "investment_stage": "미확인",
            "master_as_of_date": None,
        }
        return ClassificationResult(profile, category, current_company)

    def _classify(self, company: dict[str, Any], as_of_date: str) -> ClassificationResult:
        requested = date.fromisoformat(as_of_date)
        snapshot = date.fromisoformat(self.catalog.as_of_date)
        if requested < snapshot:
            raise ValueError(
                f"Company master snapshot {snapshot} is newer than requested date {requested}"
            )

        classification = company["classification"]
        form_key = classification.get("primary_form")
        if form_key is not None and form_key not in FORMS:
            raise ValueError(f"Unknown Physical AI form in master: {form_key}")
        form = FORMS.get(form_key)
        review_required = form is None or classification.get("status") == "proposed_needs_review"
        source_ids = list(dict.fromkeys(
            classification.get("source_ids", [])
            + company.get("business_model", {}).get("source_ids", [])
            + company.get("investment_stage", {}).get("source_ids", [])
            + company.get("listing_status", {}).get("source_ids", [])
        ))
        source_urls = list(dict.fromkeys(
            url for source_id in source_ids
            if (url := self.catalog.source_url(source_id))
        ))
        products = company.get("products", [])
        secondary_forms = list(dict.fromkeys(
            FORMS[product["form"]].label
            for product in products
            if product.get("form") in FORMS and product["form"] != form_key
        ))
        label = form.label if form else "분류 검토 필요"
        segments = company.get("target_customers", {}).get("segments", [])
        roles = company.get("classification", {}).get("supply_roles", [])
        profile = CompanyProfile(
            company_id=company["id"],
            company_name=company["canonical_name"],
            physical_ai_type=label,
            stage=company.get("investment_stage", {}).get("value") or "미확인",
            as_of_date=requested,
            listing_status=company.get("listing_status", {}).get("value"),
            business_model=company.get("business_model", {}).get("description"),
            classification_status=classification.get("status", "unverified"),
            supply_roles=roles,
            source_ids=source_ids,
            source_urls=source_urls,
        )
        category = MarketCategory(
            industry="Physical AI / Robotics",
            sub_industry=label,
            target_market=segments,
            customer_type=segments,
            analysis_scope=[company.get("business_model", {}).get("description", "미확인")],
            secondary_forms=secondary_forms,
            priority_metrics=list(form.priority_metrics) if form else [],
            review_required=review_required,
        )
        current_company = {
            "company_id": company["id"],
            "canonical_name": company["canonical_name"],
            "listing_status": profile.listing_status,
            "investment_stage": profile.stage,
            "business_model": profile.business_model,
            "target_customer_segments": segments,
            "supply_roles": roles,
            "products": [
                {
                    "name": product["name"],
                    "form": product.get("form"),
                    "status": product.get("status"),
                }
                for product in products
            ],
            "classification_status": profile.classification_status,
            "primary_form": form_key,
            "source_ids": source_ids,
            "source_urls": source_urls,
            "master_as_of_date": self.catalog.as_of_date,
            "evidence_index_path": company.get("evidence_index_path"),
        }
        return ClassificationResult(profile, category, current_company)
