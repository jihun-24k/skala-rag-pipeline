# C 시장·경쟁 에이전트

핵심 질문: 시장이 충분히 크며, 해당 회사가 경쟁할 수 있는 근거가 있는가?

입력은 A의 `company_profile`과 선택적 `market_category`. 출력은 `market_analysis`, `competitor_analysis`, `evidence`. 점수 부여와 투자 판단은 수행하지 않음.

## 참고한 수업 예제

- `ai-service/langchain-v1/15-RAG/01-RAG-Basic.ipynb`: 문서 분할 → 검색 → context 기반 답변
- `ai-service/langchain-v1/14-Retriever/08-Kiwi-BM25Retriever.ipynb`: BM25 검색과 한국어 검색 고려
- `ai-service/langgraph-v1/10-Agent/05-Strucutred-Output.ipynb`: Pydantic 스키마와 `ToolStrategy` 구조화 응답

현재 검색기는 외부 임베딩 호출 없는 로컬 BM25 구현. 한국어 단어와 2글자 토큰 사용. 수업의 Kiwi·FAISS 앙상블을 그대로 구현한 것은 아님.

## 처리 흐름

1. A의 기업 ID·형태·기준일 수신. `review_required=True`인 경우 분류 검토 반환
2. 산업 공통 자료를 형태 태그로 제한하여 검색
3. 기업 자료를 확인된 회사 ID로 제한하여 검색. 경쟁사 자료는 `competitor_ids`로 명시한 경우 추가 검색
4. 기준일 이후 게재·관측 자료와 E등급·미래계획 자료 제외
5. 검색 청크, 원문 URL, 출처 등급, 회사 식별자, 날짜를 모델에 전달
6. 시장 정의·전망·규모·고객·사업 실적·기회·위험·경쟁 비교를 구조화 생성
7. 인용 ID와 저장된 본문 내 정확한 구절 확인. 검증 실패 주장은 결과에서 제외
8. 세 출력 반환. 경쟁 비교는 그래프의 `competitor_analysis`에 저장하고, 후속 에이전트가 받는 `MarketAssessment.findings`에도 포함

산업 자료는 저장소 한 곳에 보관하고 여러 기업이 재사용. 같은 로봇 형태라는 이유만으로 타사를 경쟁사로 자동 확정하지 않음.

## 바로 실행: API 호출 없는 검색 확인

프로젝트 루트에서 실행:

```bash
PYTHONPATH=src python -m skala_rag.agents.market_competition \
  --company-id neubility --as-of-date 2026-09-30
```

기존 `자료조사/data/source_manifest.json`의 `canonical_paths`로 실제 MD 본문을 읽고, 해당 파일이 없으면 manifest의 조사 요약 사용. 특허·논문 원문을 자동 다운로드하거나 웹을 새로 검색하지 않음.

모델 미설정 시 `analysis_status=retrieval_only`. 검색한 근거와 부족 정보만 반환하며 시장 분석문을 임의 생성하지 않음. 등록되지 않은 회사도 아래 Python 방식으로 새 자료와 프로필을 주입하면 처리 가능.

## 모델을 연결한 사용

`langchain`은 선택 의존성. `uv sync --extra market-llm` 후 사용하는 모델 제공자의 연동 패키지·인증정보 별도 설정. 모델과 키를 코드에 하드코딩하지 않음.

```python
from skala_rag.agents.market_competition import (
    MarketCompetitionAgent, LangChainMarketGenerator,
    LocalMarketRetriever, load_documents,
)

# model: 수업 예제 방식으로 미리 구성한 LangChain 채팅 모델
c_agent = MarketCompetitionAgent(
    retriever=LocalMarketRetriever(load_documents()),
    generator=LangChainMarketGenerator(model),
)

# a_result: A 에이전트의 반환 결과
result = c_agent(a_result.company_profile, a_result.market_category)
print(result.market_analysis.model_dump())
print(result.competitor_analysis.model_dump())
print([item.model_dump() for item in result.evidence])

# InvestmentAgents의 다른 역할은 기존 인스턴스 유지
# InvestmentAgents(..., analyze_market=c_agent, ...)
```

CLI에서도 `--model '제공자:모델명'`을 지정하면 같은 생성 경로 사용. 실제 원격 LLM의 품질 검증은 아직 미실행. 로컬 검증은 가짜 모델의 tool call을 이용한 실제 LangChain 구조화 출력 연결과 모의 생성기를 이용한 인용 검증 기준.

## 신규 자료와 산업 공통 자료 넣기

`자료조사/data/market_documents.jsonl`에 `MarketDocument` 객체를 한 줄씩 저장하거나, `LocalMarketRetriever(documents)`에 직접 전달. 기존 기업 마스터 등록을 요구하지 않음. 회사 동일성 확인은 업스트림 책임이며 `company_ids`는 A가 반환한 `company_id`와 정확히 일치해야 함.

다음은 **형식 설명용 가상 자료**. 실제 자료로 교체 후 저장. 테스트 수치를 실데이터에 자동 등록하지 않음.

```python
from skala_rag.agents.market_competition import MarketDocument

industry_document = MarketDocument(
    document_id="industry_report_001",
    title="보고서 제목",
    text=report_text,                  # 실제 확보한 본문 또는 조사 요약
    source_url=original_url,           # 원문 페이지 URL 필수
    source_grade="A",                 # 실제 출처에 맞게 지정
    source_type="government_report",
    content_kind="source_excerpt",   # 요약이면 research_summary
    scope="industry",
    forms=["mobile_robot"],           # taxonomy 키 또는 정확한 형태명
    published_at="2026-08-01",
    observed_at="2026-09-30",
    locator="p.12",
)

company_document = MarketDocument(
    document_id="company_customer_001",
    title="고객사 도입 사례",
    text=customer_case_text,
    source_url=customer_original_url,
    source_grade="B",
    source_type="customer_announcement",
    scope="company",
    company_ids=[a_result.company_profile.company_id],
    observed_at="2026-09-30",
)

retriever = LocalMarketRetriever([
    *load_documents(), industry_document, company_document,
])
```

문서 ID 중복은 오류로 처리. 조회 시 산업·기업·명시 경쟁사 경로별 기본 4청크씩 검색. 실제 기존 MD는 회사 관련 자료 중심이며, 형태별 산업 공통 보고서는 별도로 등록 필요. 일반 회사 자료를 산업 시장규모 근거로 자동 승격하지 않음.

## 출력 항목

- `market_analysis`: 상태, 시장 정의, 전망, TAM/SAM/SOM, 고객군, 기회, 리스크, 실적, 경쟁사명, 주장별 근거 ID, 부족 정보
- `competitor_analysis`: 경쟁사명, 비교 설명, 근거 ID, 비교 자료 부족 정보
- `evidence`: 검증된 인용 구절, 원문 URL, 문서 위치, 출처 유형·등급

생성 성공 상태도 `draft_requires_review`. TAM/SAM/SOM은 값·단위·기준연도·지역·시장 범위·산출 방법을 요구하고, 값·단위·연도가 인용문에 있는지 검사. 누락 시 해당 수치를 제외하고 `missing_facts` 기록. 회사 성과와 시장 전망, 보고서별 범위 차이는 프롬프트에서 구분하도록 지시.

## 한계와 날짜 정책

- 인용 검증은 청크·구절 존재 확인. 그 구절이 주장 전체를 논리적으로 입증하는지, 원문이 사실인지 자동 보장하지 않음. `Evidence.confidence=0`, `stance=unknown`은 사실 검증 미평가 표기
- 기존 MD는 조사 요약이므로 인용문이 원문 웹페이지의 직접 인용이라는 의미가 아님. 본문 유형을 모델에 전달
- 자동 웹 수집, 원문 URL 생존 확인, 벡터 검색, 자동 경쟁사 발굴은 현재 범위 밖
- 날짜를 알 수 없는 문서는 관측일 기준. 과거 시점 요청에는 당시 관측되지 않은 자료 제외
- manifest의 `2026`·`2026-08` 같은 불완전 게재일은 각각 연말·월말을 보수적인 상한으로 사용. 원래 표기는 `published_at_raw` 보존
- 미래계획이 포함됐다고 표시된 문서는 전체 제외하므로 함께 적힌 과거 실적도 검색에서 빠질 수 있음. 원문을 사실·계획 단위로 분리해 별도 문서로 넣으면 개선 가능
- 생성기 오류·잘못된 응답 스키마는 예외로 전달. 성공한 빈 보고서로 숨기지 않음

## 파일

- `documents.py`: 입력 문서 스키마, 기존 MD·JSONL 로더
- `retrieval.py`: 청크 분할, BM25, 회사·형태·날짜 필터
- `generation.py`: 프롬프트, 생성 스키마, LangChain 어댑터
- `agent.py`: C 실행과 인용 검증, 세 출력 구성
- `__main__.py`: 로컬 실행 진입점
