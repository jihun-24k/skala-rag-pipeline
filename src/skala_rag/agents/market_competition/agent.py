"""C: retrieve market evidence, generate cited analysis, never assign investment scores."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from skala_rag.agents.interfaces import AnalysisResult
from skala_rag.agents.market_classification.taxonomy import FORMS
from skala_rag.models import (CompanyProfile, CompetitorAnalysis, CompetitorComparison,
                              Evidence, MarketAssessment, MarketCategory, MarketFinding, MissingFact)
from .documents import load_documents
from .generation import MarketDraft, MarketGenerator
from .retrieval import LocalMarketRetriever


@dataclass(frozen=True, slots=True)
class MarketAnalysisResult(AnalysisResult[MarketAssessment]):
    competitor_analysis: CompetitorAnalysis = field(default_factory=CompetitorAnalysis)

    @property
    def market_analysis(self) -> MarketAssessment:
        return self.assessment


class MarketCompetitionAgent:
    def __init__(self, retriever: LocalMarketRetriever | None = None,
                 generator: MarketGenerator | None = None, *, research_root: Path | None = None,
                 top_k: int = 4):
        if top_k < 1:
            raise ValueError('top_k must be positive')
        self.retriever = retriever if retriever is not None else LocalMarketRetriever(load_documents(research_root))
        self.generator = generator
        self.top_k = top_k

    def __call__(self, company_profile: CompanyProfile, market_category: MarketCategory,
                 query: str = '') -> MarketAnalysisResult:
        return self.analyze(company_profile, market_category, query=query)

    def analyze(self, company_profile: CompanyProfile, market_category: MarketCategory | None = None,
                *, query: str = '', competitor_ids: list[str] | None = None) -> MarketAnalysisResult:
        profile = CompanyProfile.model_validate(company_profile)
        category = market_category or MarketCategory(industry='Physical AI', sub_industry=profile.physical_ai_type)
        if category.review_required or profile.physical_ai_type in {'미확정', '미확인', '분류 검토 필요', ''}:
            missing = MissingFact(field='classification', reason='A 기업 분류 검토 완료 후 시장 분석 필요')
            return MarketAnalysisResult(MarketAssessment(analysis_status='classification_review', missing_facts=[missing]),
                                        [], CompetitorAnalysis(missing_facts=[missing]))
        forms = {profile.physical_ai_type, category.sub_industry, *category.secondary_forms}
        forms.update(key for key, form in FORMS.items() if form.label in forms)
        industry_query = ' '.join([profile.physical_ai_type, *category.target_market,
                                  '시장 규모 수요 성장 전망 규제 경쟁 market demand growth', query])
        company_query = ' '.join([profile.company_name, profile.business_model or '',
                                 '제품 고객 도입 계약 경쟁 차별화 market customer competitor', query])
        common = dict(forms=forms, as_of_date=profile.as_of_date, limit=self.top_k)
        industry = self.retriever.search(industry_query, scope='industry', company_ids=set(), **common)
        company = self.retriever.search(company_query, scope='company', company_ids={profile.company_id}, **common)
        rival_ids = set(competitor_ids or []) - {profile.company_id}
        rivals = self.retriever.search(industry_query, scope='company', company_ids=rival_ids, **common) if rival_ids else []
        chunks = list({c.chunk_id: c for c in [*industry, *company, *rivals]}.values())
        available = {c.chunk_id: c for c in chunks}
        sources = list(dict.fromkeys(c.document.source_url for c in chunks))
        missing = []
        if not industry:
            missing.append(MissingFact(field='industry_evidence', reason='해당 형태의 산업 공통 자료 미검색',
                                       attempted_queries=[industry_query], sources_checked=sources))
        if not company:
            missing.append(MissingFact(field='company_evidence', reason='동일 회사의 시장·고객 자료 미검색',
                                       attempted_queries=[company_query], sources_checked=sources))
        payload = {
            'company_profile': profile.model_dump(mode='json'),
            'market_category': category.model_dump(mode='json'), 'query': query,
            'retrieved_context': [{
                'chunk_id': c.chunk_id, 'title': c.document.title, 'text': c.text,
                'scope': c.document.scope, 'company_ids': c.document.company_ids,
                'source_url': c.document.source_url, 'source_grade': c.document.source_grade,
                'source_type': c.document.source_type,
                'content_kind': c.document.content_kind,
                'published_at': str(c.document.published_at) if c.document.published_at else None,
                'published_at_raw': c.document.published_at_raw,
                'observed_at': c.document.observed_at.isoformat(),
            } for c in chunks],
        }
        evidence: dict[str, Evidence] = {}
        market = MarketAssessment(analysis_status='insufficient_evidence', missing_facts=missing)
        missing = market.missing_facts
        competitors = CompetitorAnalysis()
        if self.generator is None or not chunks:
            if self.generator is None:
                market.analysis_status = 'retrieval_only'
                missing.append(MissingFact(field='generation', reason='구조화 생성 모델 미설정; 검색 근거만 반환'))
            for c in chunks:
                evidence[c.chunk_id] = Evidence(
                    evidence_id=c.chunk_id, claim_text=c.text, stance='unknown',
                    source_type=c.document.source_type, source_grade=c.document.source_grade,
                    source_uri=c.document.source_url,
                    locator=f'{c.document.locator or c.document.document_id}#char={c.offset}', confidence=0,
                )
            market.evidence_ids = list(evidence)
            competitors.missing_facts.append(MissingFact(field='competitors', reason='인용된 경쟁 비교 분석 미생성'))
            return MarketAnalysisResult(market, list(evidence.values()), competitors)

        # Provider/validation failures surface explicitly; they are not successful empty reports.
        draft = MarketDraft.model_validate(self.generator.generate(payload))
        field_map = {'definition': 'market_definition', 'outlook': 'outlook', 'customer': 'customer_segments',
                     'traction': 'traction', 'opportunity': 'opportunities', 'risk': 'market_risks'}
        for claim in draft.claims:
            invalid = any(ref.chunk_id not in available or ref.quote not in available[ref.chunk_id].text
                          for ref in claim.citations)
            if claim.topic == 'competition' and not claim.competitor_name:
                invalid = True
            if claim.topic in {'tam', 'sam', 'som'}:
                size = claim.market_size
                quoted = ' '.join(ref.quote for ref in claim.citations)
                if size is None or any(value not in quoted for value in
                                       [size.value, size.unit, str(size.base_year)]):
                    invalid = True
            if invalid:
                missing.append(MissingFact(field=claim.topic, reason='인용·경쟁사명 또는 시장규모 필수 정보 검증 실패; 주장 제외'))
                continue
            ids = []
            for ref in claim.citations:
                c = available[ref.chunk_id]
                eid = 'market:' + hashlib.sha256((c.chunk_id+'\0'+ref.quote).encode()).hexdigest()[:20]
                ids.append(eid)
                evidence[eid] = Evidence(
                    evidence_id=eid, claim_text=ref.quote, stance='unknown',
                    source_type=c.document.source_type, source_grade=c.document.source_grade,
                    source_uri=c.document.source_url,
                    locator=f'{c.document.locator or c.document.document_id}#char={c.offset+c.text.index(ref.quote)}',
                    confidence=0,  # Exact quote validation is not factual/semantic confidence.
                )
            claim_text = claim.text
            if claim.topic in {'tam', 'sam', 'som'}:
                size = claim.market_size
                claim_text = (f'{size.base_year}년 {size.geography} / {size.segment}: '
                              f'{size.value} {size.unit} ({size.methodology})')
            market.findings.append(MarketFinding(topic=claim.topic, text=claim_text, evidence_ids=ids))
            if claim.topic in field_map:
                getattr(market, field_map[claim.topic]).append(claim.text)
            elif claim.topic in {'tam', 'sam', 'som'}:
                old = getattr(market, claim.topic)
                setattr(market, claim.topic, f'{old}\n{claim_text}' if old else claim_text)
            elif claim.topic == 'competition':
                competitors.comparisons.append(CompetitorComparison(
                    competitor_name=claim.competitor_name, comparison=claim.text, evidence_ids=ids))
                if claim.competitor_name not in market.competitors:
                    market.competitors.append(claim.competitor_name)
        for name in ['tam', 'sam', 'som']:
            if not getattr(market, name):
                missing.append(MissingFact(field=name, reason='범위·기준연도·단위·산출근거를 갖춘 인용 수치 미확보',
                                           sources_checked=sources))
        missing.extend(MissingFact(field='limitation', reason=s) for s in draft.limitations)
        if not competitors.comparisons:
            competitors.missing_facts.append(MissingFact(field='competitors', reason='인용 검증을 통과한 경쟁 비교 미확보', sources_checked=sources))
        market.evidence_ids = list(evidence)
        market.analysis_status = 'draft_requires_review' if market.findings else 'insufficient_evidence'
        return MarketAnalysisResult(market, list(evidence.values()), competitors)
