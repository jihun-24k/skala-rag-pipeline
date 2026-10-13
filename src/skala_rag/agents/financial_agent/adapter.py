"""Convert provider financial values to the graph contract with provenance."""
from datetime import date

from skala_rag.agents.interfaces import AnalysisResult
from skala_rag.models import Evidence, FinancialAssessment, MissingFact
from .models.schemas import CompanyRef
from .agent.financial_agent import build_default_agent


def unavailable_financials(profile, tech, market):
    """Explicit offline mode: do not instantiate providers or make HTTP requests."""
    return AnalysisResult(FinancialAssessment(missing_facts=[MissingFact(
        field='financial_statements', reason='재무 API 미사용; --financial-api로 활성화')]))


class FinancialAnalyzerAdapter:
    def __init__(self, agent=None):
        self.agent = agent or build_default_agent()

    def __call__(self, profile, tech, market):
        collected = self.agent.collector.collect(CompanyRef(
            company_id=profile.company_id, company_name=profile.company_name))
        normalized = self.agent.normalizer.normalize(collected.financials)
        values, evidence, missing, periods = {}, [], [], {}
        for field in ('revenue', 'operating_income', 'total_assets', 'total_liabilities', 'total_funding'):
            item = getattr(normalized, field)
            if item is None or item.value is None or not item.as_of:
                missing.append(MissingFact(field=field, reason='기준일과 출처가 있는 재무 수치 미확보'))
                continue
            try:
                period = date.fromisoformat(item.as_of)
            except ValueError:
                missing.append(MissingFact(field=field, reason='재무 기준일 형식 확인 필요'))
                continue
            if period > profile.as_of_date:
                missing.append(MissingFact(field=field, reason='분석 기준일 이후 재무자료 제외'))
                continue
            eid = f'financial:{profile.company_id}:{item.source}:{item.as_of}:{field}'
            uri = {'dart': 'https://opendart.fss.or.kr/',
                   'fsc': 'https://www.data.go.kr/', 'kind': 'https://kind.krx.co.kr/'}[item.source]
            if item.source == 'dart' and item.receipt_no:
                uri = f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.receipt_no}'
            values[field] = f'{item.value:g} {item.unit or "단위 미확인"} ({item.as_of})'
            periods[field] = (item.as_of, item.statement_scope, item.unit)
            evidence.append(Evidence(evidence_id=eid, claim_text=f'{field}: {values[field]}',
                stance='support', source_type='regulatory', source_grade='A', source_uri=uri,
                locator=f'{item.receipt_no or item.source}:{field}:{item.as_of}',
                company_id=profile.company_id, value=item.value, confidence=None))
        # Preserve annual comparative amounts from the SAME filing/scope/unit.
        # Missing values never become zero; quarterly amounts are not annualized.
        from skala_rag.models.investment import FinancialObservation
        import math
        for e in list(evidence):
            field = e.evidence_id.rsplit(':', 1)[-1]
            item = getattr(normalized, field)
            if (field == 'total_funding' or item.report_type != 'annual'
                    or not item.statement_scope or not item.unit or not item.receipt_no
                    or e.value is None or not math.isfinite(e.value)):
                continue
            e.financial_observation = FinancialObservation(metric=field,
                period_end=item.as_of, unit=item.unit, statement_scope=item.statement_scope)
            if item.previous_value is None or not math.isfinite(item.previous_value) or not item.previous_as_of:
                continue
            try:
                prior = date.fromisoformat(item.previous_as_of)
            except ValueError:
                continue
            current = date.fromisoformat(item.as_of)
            if prior >= current or prior.year != current.year - 1 or prior.month != current.month:
                continue
            previous = e.model_copy(deep=True)
            previous.evidence_id = e.evidence_id + ':previous'
            previous.value = item.previous_value
            previous.financial_observation = e.financial_observation.model_copy(update={'period_end': prior})
            previous.claim_text = f'{field}: {item.previous_value:g} {item.unit} ({prior.isoformat()}); 동일 공시의 전기 비교 수치'
            previous.locator = f'{item.receipt_no}:{field}:{prior.isoformat()}:comparative'
            evidence.append(previous)
        # Include comparative points in the evidence contract as well.
        for report in collected.source_reports:
            if report.error or report.status.value != 'available':
                missing.append(MissingFact(field=f'source:{report.source}',
                    reason=report.status.value, sources_checked=[report.source]))
        # Partial provider data is usable only when the minimum balance sheet and
        # income data are present. Missing optional fields remain explicit.
        complete = ('total_assets' in values and 'revenue' in values
                    and periods['total_assets'] == periods['revenue']
                    and periods['revenue'][2] is not None)
        status = 'available' if complete else 'unavailable'
        if not complete:
            missing.append(MissingFact(field='financial_statements',
                reason='동일 기준일·연결범위·단위의 매출과 총자산 확인 필요'))
        return AnalysisResult(FinancialAssessment(status=status, **values,
            evidence_ids=[e.evidence_id for e in evidence], missing_facts=missing), evidence)
