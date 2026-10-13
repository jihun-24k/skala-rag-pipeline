"""Separate post-generation quality gate with explicit unknown semantic verdicts."""
from __future__ import annotations

import re

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
        from skala_rag.agents.report import attach_financial_charts, assess_business_report
        expected_charts = attach_financial_charts(report, evidence).financial_charts
        invalid_charts = report.financial_charts != expected_charts
        expected_business = assess_business_report(report, evidence)
        invalid_business = (report.business_scores != expected_business.business_scores or
                            report.business_assessment != expected_business.business_assessment)
        grounded = 'fail' if invalid_business or invalid_charts or bad_ids or bad_refs or bad_urls or no_claims or unused_refs or summary_only else 'pass'
        items = [QualityItem(criterion='groundedness', verdict=grounded,
            reason=('근거 연결 오류: 미등록 ID=' + str(sorted(bad_ids)) + '; 참고문헌 누락=' + str(sorted(bad_refs))
                    + '; URL 불일치=' + str(bad_urls) + '; 미사용 참고문헌=' + str(sorted(unused_refs))
                    + '; SUMMARY 전용 ID=' + str(sorted(summary_only))
                    + f'; 분석 없음={no_claims}; 차트 불일치={invalid_charts}; 점수 불일치={invalid_business}') if grounded == 'fail'
                else '주장의 모든 ID와 REFERENCE 연결 확인', target='F' if grounded == 'fail' else None)]
        text = report.summary + '\n' + '\n'.join(c.text for c in claims)
        recommended = bool(re.search(r'(투자를?\s*추천|구매를?\s*추천|최고의\s*기술|무조건\s*우수)', text))
        items.append(QualityItem(criterion='neutrality', verdict='fail' if recommended else 'pass',
            reason='특정 기술 추천·우열 표현 검토 필요' if recommended else '명시적 추천 표현 없음',
            target='F' if recommended else None))
        # Bias is selective presentation, not a minimum number of publishers or
        # third-party replication requirement. The semantic judge checks whether
        # known contrary evidence and source limitations were fairly represented.
        items.append(QualityItem(criterion='bias', verdict='pass',
            reason='출처 수·도메인 수·independent 여부는 통과 조건이 아님; 알려진 반대 근거 누락과 출처 성격 왜곡을 의미 평가'))
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
                # Format is measured from the actual renderer; the semantic
                # judge must not mistake JSON sections 2-13 for missing 1/14.
                merged.append(rule if rule.verdict == 'fail' or item.criterion == 'format' else item)
        return QualityVerdict(items=merged, report_revision=state['report_revision'])
