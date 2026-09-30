# A 접수·시장분류 에이전트

기업 정보 객체를 받아 Physical AI 형태를 분류하고 `current_company`, `company_profile`, `market_category`를 반환하는 A 에이전트. 신규 기업도 입력 가능. 기술력·시장성 평가와 투자 점수 계산은 후속 역할 담당.

## 기본 입력: 기업 정보 객체

`query`는 필수 항목이 아님. 아래는 가상의 기업·URL을 사용한 실행 예시이며, 실제 사용 시 수집기가 전달한 회사명·자료 본문·원문 URL로 교체.

```python
from skala_rag.agents.market_classification import MarketClassificationAgent

agent = MarketClassificationAgent()
incoming_company = {
    "company_name": "새빛로봇",
    "aliases": ["Saebit Robotics Inc."],
    "evidence": [{
        "title": "새빛로봇 제품 소개",
        "text": "새빛로봇은 시설 점검용 4족 보행 로봇을 개발한다.",
        "url": "https://example.com/products",  # 실제 원문 URL로 교체
        "official": True,  # 업스트림에서 공식 회사 자료로 확인한 경우만 True
    }],
}
result = agent.classify_company(incoming_company, as_of_date="2026-09-30")
print(result.company_profile.model_dump())
print(result.market_category.model_dump())
print(result.current_company)
```

예시 결과: `primary_form=legged_robot`, `physical_ai_type=다족보행 로봇`, `classification_status=proposed_needs_review`, `review_required=True`. 가설 분류와 확정 상태의 구분.

### 객체 필드

- `company_name` 또는 `name`: 회사명. 등록 기업이면 `company_id` 또는 `id`만 전달 가능
- `aliases`: 선택 항목. 동일 회사로 확인한 영문명·별칭 목록
- `evidence`: 선택 항목. 출처별 `title`, `text`(또는 `snippet`), `url`(또는 `source_url`), `official` 목록. 자료 본문 또는 제목에 회사명·확인된 별칭 포함 필요
- `as_of_date`: 함수의 별도 필수 인자. ISO 날짜
- `official`: 호출자가 확인한 공식 회사 자료 여부. A가 도메인 소유권을 자동 검증한다는 의미가 아님

### 입력별 처리 순서

1. **`evidence` 필드 있음**: 등록 여부와 무관하게 전달 자료로 새 분류. 등록 기업은 기존 ID만 유지하고, 기존 형태를 답으로 재사용하지 않음. 빈 목록·유효하지 않은 출처만 있으면 자료 부족 반환. 웹 검색이나 기존 마스터로 자동 대체하지 않음
2. **`evidence` 필드 없음 + 등록 기업**: 기존 기업 마스터 조회
3. **`evidence` 필드 없음 + 미등록 기업**: 검색 제공자 호출. 검색 설정도 없으면 `insufficient_evidence` 반환

신규 분류 결과는 마스터에 자동 저장하지 않음. 검토 후 저장·승격은 별도 절차.

## 여러 기업 및 그래프 입력

```python
state = {
    "as_of_date": "2026-09-30",
    "candidate_companies": [incoming_company],
    "current_index": 0,
}
result = agent.classify_state(state)
# InvestmentAgents(classify_market=agent, ...)로 구성한 그래프에도 동일 state 전달
# graph.invoke(state)
```

`current_index`는 이번 호출에서 처리할 회사 한 곳을 선택. 전체 목록을 자동 순회하지 않음. 자연어 `query`는 기존 호출과의 호환용이며 후보 목록이 있으면 목록이 우선.

## 자료 출처와 분류 방식

- 등록 기업: 인접한 `자료조사/data/company_master.json` 및 `source_manifest.json`의 출처 URL 조회. 기업별 MD 본문 전체를 런타임에 검색하는 RAG는 아직 미구현
- 신규 자료: 업스트림 수집기의 `evidence` 본문과 URL 사용. 특허·논문 등을 직접 수집하는 기능은 별도
- 기업 이름만으로 신규 조사: `BRAVE_SEARCH_API_KEY` 설정 시 [Brave Web Search API](https://api-dashboard.search.brave.com/documentation/services/web-search) 검색 제목·요약·URL 사용. 원문 자동 크롤링은 미구현
- 형태: `taxonomy.py`의 열 가지 형태에 대해 규칙 기반 키워드 추출. 띄어쓰기 변형 및 `휴머노이드`, `로봇팔` 등 지원
- 동일 회사: 법인 표기·공백 정규화 및 명시적 영문 별칭 사용. 동명의 다른 법인까지 자동으로 검증하는 기능은 미구현
- 단일 형태 제안: 회사명 일치와 공식 자료 한 곳 또는 서로 다른 도메인 두 곳의 동일 형태 신호 필요. 다른 도메인이 독립된 사실 검증을 의미하지는 않음
- 복수 형태: 첫 번째 일치로 확정하지 않고 `conflicting_forms`, `candidate_forms`, `secondary_forms`로 보존

`SKALA_RESEARCH_ROOT` 환경변수로 자료조사 위치 지정 가능. PostgreSQL로 이전할 때는 `CompanyCatalog`의 `list_companies`, `get_company`, `source_url`, `as_of_date`를 구현해 주입.

## 검토 분기와 한계

- 새 자료를 처리한 결과는 항상 `review_required=True`. 그래프는 B·C 및 후속 평가 호출을 건너뛰고 `추가 실사` 보고서 반환. 미평가 점수는 `None`
- 등록 마스터도 형태 미확정 또는 `proposed_needs_review` 상태이면 검토 분기
- 규칙 기반 초안 분류이며, LLM이 문맥·부정문·타사 제품 언급·미래 계획을 이해하는 분류기는 아님. 회사명만으로 모든 신규 기업의 정확한 확정 분류를 보장하지 않음
- 이름만 입력하는 실제 웹 검색은 API 키 설정 및 별도 통합 확인 필요. 로컬 검증은 전달 자료와 모의 검색 제공자 기준
- 등록 마스터 스냅샷보다 이른 기준일 조회는 거부. 전달 자료의 게재일·시점은 아직 자동 검증하지 않으므로 과거 기준 평가 시 업스트림에서 자료 시점 필터링 필요
- 상장 여부·투자 단계는 신규 자료 분류에서 `미확인` 상태. 형태 키워드로 추정하지 않음
- A~E 자료 등급과 A 에이전트의 역할은 다른 개념
