"""Separate post-generation quality gate with explicit unknown semantic verdicts."""
from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlsplit

from skala_rag.models.orchestration import QualityItem, QualityVerdict, VIEWS


class ReportEvaluator:
    def __init__(self, judge=None, page_counter=None):
        self.judge, self.page_counter = judge, page_counter

    def __call__(self, request, state):
        report = state['report']
        evidence = {e.evidence_id: e for e in state['evidence']}
        claims = [c for p in report.perspectives for c in p.findings]
        ids = {eid for c in claims for eid in c.evidence_ids}
        bad_ids = ids - evidence.keys()
        bad_refs = ids - report.references.keys()
        bad_urls = [eid for eid in ids & evidence.keys() & report.references.keys()
                    if report.references[eid] != evidence[eid].source_uri]
        no_claims = not claims
        grounded = 'fail' if bad_ids or bad_refs or bad_urls or no_claims else 'pass'
        items = [QualityItem(criterion='groundedness', verdict=grounded,
            reason='유효한 근거·REFERENCE가 없는 주장 또는 분석 내용 없음' if grounded == 'fail'
                else '주장의 모든 ID와 REFERENCE 연결 확인', target='F' if grounded == 'fail' else None)]
        text = report.summary + '\n' + '\n'.join(c.text for c in claims)
        recommended = bool(re.search(r'(투자를?\s*추천|구매를?\s*추천|최고의\s*기술|무조건\s*우수)', text))
        items.append(QualityItem(criterion='neutrality', verdict='fail' if recommended else 'pass',
            reason='특정 기술 추천·우열 표현 검토 필요' if recommended else '명시적 추천 표현 없음',
            target='F' if recommended else None))
        sources = {evidence[eid].source_event_id or evidence[eid].source_uri
                   for eid in ids & evidence.keys()}
        domains = {urlsplit(evidence[eid].source_uri).hostname for eid in ids & evidence.keys()}
        independent = any(evidence[eid].independent is True for eid in ids & evidence.keys())
        balanced = any(evidence[eid].stance in ('contradict', 'unknown') for eid in ids & evidence.keys())
        biased = len(sources) < 2 or len(domains) < 2 or not balanced
        items.append(QualityItem(criterion='bias', verdict='fail' if biased else 'pass' if independent else 'unknown',
            reason='독립 출처·반대/불확실 근거 추가 조사 필요' if biased else
                '출처 분산과 반대/불확실 근거 확인' if independent else '출처 독립성의 의미 검증 필요',
            target='C' if biased else None,
            questions=['기업 발표와 독립적인 출처 및 불리한 근거를 추가 조사하세요.'] if biased else []))
        present = Counter(p.view for p in report.perspectives if p.findings)
        missing = [view for view in VIEWS if present[view] != 1]
        duplicate = len({p.view for p in report.perspectives}) != len(report.perspectives)
        excessive = self.page_counter is not None and self.page_counter(report) > 10
        coverage = 'fail' if missing or duplicate or excessive else 'pass'
        target = 'F' if excessive or duplicate else ('B' if 'technology' in missing or 'domain' in missing else 'C')
        items.append(QualityItem(criterion='coverage', verdict=coverage,
            reason='10쪽 초과' if excessive else '누락·중복 관점: ' + ', '.join(missing)
                if coverage == 'fail' else '네 관점의 인용된 분석 확인',
            target=target if coverage == 'fail' else None,
            questions=['네 관점을 유지하면서 10쪽 이내로 간결하게 작성하세요.'] if excessive else []))
        rules = {item.criterion: item for item in items}
        if self.judge is None:
            # Structural checks are not semantic confirmation.
            merged = [item if item.verdict == 'fail' else item.model_copy(update={
                'verdict': 'unknown', 'reason': item.reason + '; 의미 평가 모델 미설정'}) for item in items]
        else:
            semantic = QualityVerdict.model_validate(self.judge(report, state, request))
            if semantic.report_revision != state['report_revision']:
                raise ValueError('Semantic Judge evaluated a stale report revision')
            merged = []
            for item in semantic.items:
                rule = rules[item.criterion]
                merged.append(rule if rule.verdict == 'fail' else item)
        return QualityVerdict(items=merged, report_revision=state['report_revision'])
