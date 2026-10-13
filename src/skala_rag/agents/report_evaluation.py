"""Separate post-generation quality gate with explicit unknown semantic verdicts."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from skala_rag.models.orchestration import QualityItem, QualityVerdict, REPORT_OUTLINE


class ReportEvaluator:
    def __init__(self, judge=None, page_counter=None):
        self.judge, self.page_counter = judge, page_counter

    def __call__(self, request, state):
        report = state['report']
        evidence = {e.evidence_id: e for e in state['evidence']}
        from skala_rag.agents.report import evaluation_claims
        claims = evaluation_claims(report)
        body_ids = {eid for c in claims for eid in c.evidence_ids}
        summary_ids = {eid.strip() for group in re.findall(r'\[([^\[\]\n]+)\]', report.summary)
                       for eid in group.split(',')}
        ids = body_ids | summary_ids
        bad_ids = ids - evidence.keys()
        bad_refs = ids - report.references.keys()
        bad_urls = [eid for eid in ids & evidence.keys() & report.references.keys()
                    if report.references[eid] != evidence[eid].source_uri]
        no_claims = not claims
        unused_refs = report.references.keys() - ids
        summary_only = summary_ids - body_ids
        from skala_rag.agents.report import attach_financial_charts
        expected_charts = attach_financial_charts(report, evidence).financial_charts
        invalid_charts = report.financial_charts != expected_charts
        grounded = 'fail' if invalid_charts or bad_ids or bad_refs or bad_urls or no_claims or unused_refs or summary_only else 'pass'
        items = [QualityItem(criterion='groundedness', verdict=grounded,
            reason='근거·REFERENCE 불일치, 미사용 참고문헌, SUMMARY의 본문 외 인용 또는 분석 내용 없음' if grounded == 'fail'
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
        issues = []
        from skala_rag.agents.report import report_classification
        expected_classification = report_classification(state)
        if expected_classification and report.classification != expected_classification:
            issues.append('INVESTMENT SNAPSHOT에 현재 기업 분류 결과를 원형대로 표시하세요.')
        if [s.key for s in report.sections] != [key for key, _ in REPORT_OUTLINE]:
            issues.append('기존 보고서 목차 2~13을 순서대로 각각 한 번 작성하세요.')
        if not report.summary.strip():
            issues.append('본문의 핵심 결론으로 SUMMARY를 작성하세요.')
        if re.search(r'(?m)^\s*(?:#{1,6}\s|\||```|~~~)', report.summary):
            issues.append('SUMMARY는 표·하위 목차·코드 없이 핵심 요약 문단으로 작성하세요.')
        if self.page_counter is not None:
            from skala_rag.pdf_report import evaluation_summary_fits
            if not evaluation_summary_fits(report.summary):
                issues.append('SUMMARY를 반 페이지 이내로 줄이고 상세 근거는 본문에 보존하세요.')
            if self.page_counter(report) > 10:
                issues.append('기존 목차와 REFERENCE를 유지하며 중복을 줄여 전체를 10쪽 이내로 수정하세요.')
        elif len(report.summary) > 700:
            issues.append('SUMMARY가 길므로 약 400~600자로 요약하고 PDF에서 반 페이지 이내인지 확인하세요.')
        items.append(QualityItem(criterion='format', verdict='fail' if issues else 'pass',
            reason='; '.join(issues) if issues else '기존 목차·SUMMARY·분량 형식 확인',
            target='F' if issues else None, questions=issues))
        rules = {item.criterion: item for item in items}
        if self.judge is None:
            # Structural checks are not semantic confirmation.
            merged = [item if item.verdict == 'fail' or item.criterion == 'format' else item.model_copy(update={
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
