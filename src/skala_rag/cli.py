"""Command-line entrypoint for local indexing and retrieval."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from skala_rag.ingestion import (
    DocumentChunker,
    EvidenceIndexBuilder,
    QwenEmbeddingProvider,
)
from skala_rag.retrieval import FaissEvidenceRetriever, RetrievalQuery


def _device(value: str) -> str:
    if value != "auto":
        return value
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _build_command(args: argparse.Namespace) -> int:
    embedder = QwenEmbeddingProvider(
        device=_device(args.device),
        batch_size=args.batch_size,
        # The chunk text is prefixed with retrieval metadata before embedding.
        # Reserve room so a max-sized chunk is not truncated by that prefix.
        max_length=max(args.max_tokens + 128, 1024),
    )
    chunker = DocumentChunker(
        embedder.tokenizer,
        target_tokens=args.target_tokens,
        max_tokens=args.max_tokens,
        overlap_tokens=args.overlap_tokens,
    )
    manifest = EvidenceIndexBuilder(embedder, chunker=chunker).build(
        Path(args.source),
        Path(args.output),
        index_version=args.version,
    )
    print(manifest.model_dump_json(indent=2))
    return 0


def _search_command(args: argparse.Namespace) -> int:
    embedder = QwenEmbeddingProvider(device=_device(args.device), batch_size=1)
    retriever = FaissEvidenceRetriever(Path(args.index), embedder)
    hits = retriever.search(
        RetrievalQuery(
            query=args.query,
            company_id=args.company_id,
            source_grades=args.source_grade,
            dimensions=args.dimension,
            top_k=args.top_k,
            instruction=args.instruction,
        )
    )
    print(
        json.dumps(
            [hit.model_dump(mode="json") for hit in hits],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _report_command(args: argparse.Namespace) -> int:
    from skala_rag.models import InvestmentReport
    from skala_rag.agents.report import render_markdown
    payload = json.loads(args.input.read_text(encoding='utf-8'))
    report = InvestmentReport.model_validate(payload['report'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.suffix.lower() == '.pdf':
        from skala_rag.pdf_report import render_pdf
        render_pdf(report, args.output)
    elif args.output.suffix.lower() == '.md':
        args.output.write_text(render_markdown(report), encoding='utf-8')
    else:
        raise ValueError('Report output must use .pdf or .md')
    print(args.output)
    return 0


def _analyze_command(args: argparse.Namespace) -> int:
    from skala_rag.runtime import build_runtime_agents
    from skala_rag.graph import build_investment_graph, to_storage_payload
    from skala_rag.agents.report import render_markdown
    from skala_rag.pdf_report import render_pdf, register_font
    from skala_rag.agents.financial_agent.adapter import unavailable_financials
    import re
    import uuid

    # Fail early, before retrieval or paid API calls, if the PDF font is missing.
    register_font()

    model = None
    if args.model:
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model=args.model, temperature=0)
    retriever = None
    if args.retriever == 'faiss':
        if not (args.index / 'manifest.json').is_file():
            raise FileNotFoundError(f'FAISS index not found: {args.index}; run index build first')
        embedder = QwenEmbeddingProvider(device=_device(args.device), batch_size=1)
        retriever = FaissEvidenceRetriever(args.index, embedder)
    financial = None
    if not args.financial_api:
        financial = unavailable_financials
    agents = build_runtime_agents(research_root=args.research_root, retriever=retriever,
        index_count=retriever.manifest.chunk_count if retriever else 100,
        financial_analyzer=financial, model=model)
    graph = build_investment_graph(agents)
    run_dir = args.output / uuid.uuid4().hex[:12]
    run_dir.mkdir(parents=True, exist_ok=False)
    evaluated = []
    for index, company in enumerate(args.company or [None]):
        state = {'query': args.query, 'as_of_date': args.as_of_date.isoformat()}
        if company:
            state['candidate_companies'] = [{'company_name': company}]
        # Each invocation starts fresh; evidence from one candidate cannot leak.
        result = graph.invoke(state)
        payload = to_storage_payload(result)
        payload['execution'] = {'retriever': args.retriever, 'model': args.model,
            'financial_api': args.financial_api,
            'index_version': retriever.manifest.index_version if retriever else None}
        name = re.sub(r'[^\w.-]', '_', result['company_profile'].company_id)
        stem = run_dir / f'{index + 1:02d}_{name}'
        stem.with_suffix('.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        stem.with_suffix('.md').write_text(render_markdown(result['report']), encoding='utf-8')
        render_pdf(result['report'], stem.with_suffix('.pdf'),
                   title=f"{result['company_profile'].company_name} 투자 분석 보고서")
        evaluated.append({'company': result['company_profile'].company_name,
                          'decision': result['decision'].decision,
                          'json': stem.with_suffix('.json').name,
                          'markdown': stem.with_suffix('.md').name,
                          'report': stem.with_suffix('.pdf').name})
        print(f"{evaluated[-1]['company']}: {evaluated[-1]['decision']} → {stem.with_suffix('.pdf')}")
    (run_dir / 'summary.json').write_text(json.dumps(evaluated, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


def _resolve_orchestration_storage(args: argparse.Namespace) -> None:
    """Connect a moved storage bundle without copying or rebuilding its index."""
    storage = args.storage_root.expanduser().resolve() if args.storage_root else Path('storage').resolve()
    if args.storage_root and not storage.is_dir():
        raise FileNotFoundError(f'Storage directory not found: {storage}')
    args.index = args.index or storage / 'indexes/qwen3-0.6b-v1'
    args.retriever = args.retriever or ('faiss' if (args.index / 'manifest.json').is_file() else 'bm25')
    if args.storage_root and args.retriever == 'bm25' and not (args.index / 'manifest.json').is_file():
        raise FileNotFoundError(f'Storage FAISS index missing: {args.index}; specify --index')
    if args.storage_root and args.research_root is None:
        raw = storage / 'raw'
        roots = [p for p in ([raw, *sorted(raw.iterdir())] if raw.is_dir() else [])
                 if (p / 'data/company_master.json').is_file()]
        if len(roots) != 1:
            raise ValueError('Specify --research-root: storage/raw must contain one company master')
        args.research_root = roots[0]
    args.embedding_cache = storage / 'models/hub'


def _orchestrate_command(args: argparse.Namespace) -> int:
    import hashlib
    import uuid
    from langgraph.checkpoint.sqlite import SqliteSaver
    from pypdf import PdfReader
    from skala_rag.graph.supervisor_workflow import (
        build_supervisor_graph, initial_state, invoke_supervisor, supervisor_storage_payload,
    )
    from skala_rag.models.orchestration import Limits
    from skala_rag.pdf_report import register_font, render_evaluation_pdf
    from skala_rag.runtime import build_orchestration_agents, render_evaluation_markdown
    from skala_rag.tracing import TraceRecorder
    from tempfile import TemporaryDirectory

    _resolve_orchestration_storage(args)
    run_id = str(uuid.UUID(args.resume or args.run_id)) if args.resume or args.run_id else str(uuid.uuid4())
    run_dir = args.output / run_id
    if args.resume:
        if not (run_dir / 'input.json').is_file() or not (run_dir / 'checkpoints.sqlite3').is_file():
            raise FileNotFoundError('Resume requires the original input.json and checkpoints.sqlite3')
        original = json.loads((run_dir / 'input.json').read_text(encoding='utf-8'))
        query = args.query if args.query is not None else original['query']
        as_of_date = args.as_of_date.isoformat() if args.as_of_date else original['as_of_date']
        company = args.company if args.company is not None else original.get('company')
    else:
        if not args.query:
            raise ValueError('--query is required for a new orchestration run')
        query, company = args.query, args.company
        as_of_date = (args.as_of_date or date.today()).isoformat()
        if run_dir.exists():
            raise ValueError('Run directory already exists; use --resume')

    if not args.no_pdf:
        register_font()
    limits = Limits(max_attempts_per_agent=args.max_attempts,
        max_report_attempts=args.max_report_attempts, max_errors=args.max_errors,
        max_steps=args.max_steps, max_supervisor_steps=args.max_supervisor_steps)
    configuration = {'report_contract': 'assignment-v5',
        'retriever': args.retriever, 'model': args.model, 'judge_model': args.judge_model,
        'financial_api': args.financial_api, 'research_root': str(args.research_root.resolve()) if args.research_root else None,
        'index': str(args.index.resolve()) if args.retriever == 'faiss' else None,
        'no_pdf': args.no_pdf, 'limits': limits.model_dump()}
    config_version = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
    # The recorder validates tracing credentials before model/retrieval initialization.
    recorder = TraceRecorder(run_id, run_dir / 'events.jsonl', enabled=args.langsmith,
                             project=args.langsmith_project)
    model = judge_model = None
    if not args.model and not args.judge_model:
        print('검색·연결 점검 모드: 생성/의미 평가 모델이 없어 최종 보고서는 발행되지 않습니다. '
              '보고서 생성에는 --model과 해당 모델의 API 설정이 필요합니다.')
    if args.model or args.judge_model:
        from langchain_openai import ChatOpenAI
        if args.model:
            model = ChatOpenAI(model=args.model, temperature=0, max_retries=0)
        if args.judge_model:
            judge_model = ChatOpenAI(model=args.judge_model, temperature=0, max_retries=0)
    retriever = None
    index_version = None
    if args.retriever == 'faiss':
        if not (args.index / 'manifest.json').is_file():
            raise FileNotFoundError(f'FAISS index not found: {args.index}')
        cached = args.embedding_cache.is_dir()
        retriever = FaissEvidenceRetriever(args.index, QwenEmbeddingProvider(
            device=_device(args.device), batch_size=1,
            cache_folder=str(args.embedding_cache) if cached else None,
            local_files_only=cached))
    # Both retrieval modes join documents/master; version labels alone cannot
    # detect replacement of an index or its provenance with the same name.
    from skala_rag.agents.market_competition.documents import load_documents
    from skala_rag.agents.market_classification.catalog import JsonCompanyCatalog
    catalog = JsonCompanyCatalog(args.research_root)
    corpus = {'documents': [d.model_dump(mode='json') for d in load_documents(catalog.root)],
              'companies': catalog.list_companies(),
              'index': retriever.manifest.model_dump(mode='json') if retriever else None}
    index_version = args.retriever + ':' + hashlib.sha256(
        json.dumps(corpus, sort_keys=True, default=str).encode()).hexdigest()

    incoming = {'query': query, 'company': company, 'as_of_date': as_of_date,
                'config_version': config_version, 'index_version': index_version}
    if args.resume and incoming != original:
        raise ValueError('Resume input, corpus or execution configuration differs from original run')

    def page_counter(report):
        with TemporaryDirectory() as directory:
            path = render_evaluation_pdf(report, Path(directory) / 'quality.pdf')
            return len(PdfReader(str(path)).pages)

    agents = build_orchestration_agents(research_root=args.research_root, retriever=retriever,
        index_count=retriever.manifest.chunk_count if retriever else 100,
        model=model, judge_model=judge_model, financial_api=args.financial_api,
        page_counter=page_counter)
    run_dir.mkdir(parents=True, exist_ok=True)
    if not args.resume:
        (run_dir / 'input.json').write_text(json.dumps(incoming, ensure_ascii=False, indent=2), encoding='utf-8')
    config = {'configurable': {'thread_id': run_id}, 'recursion_limit': limits.max_steps * 2 + 10}
    recorder.start(resume=bool(args.resume))
    with SqliteSaver.from_conn_string(str(run_dir / 'checkpoints.sqlite3')) as checkpointer:
        graph = build_supervisor_graph(agents, checkpointer=checkpointer, recorder=recorder)
        if args.resume:
            snapshot = graph.get_state(config)
            if not snapshot.values:
                raise ValueError('No checkpoint exists for this run')
        try:
            # Disable automatic prompt/State uploads even when LANGSMITH_TRACING is set.
            # The recorder separately submits sanitized node spans.
            result = invoke_supervisor(graph, None if args.resume else initial_state(query, as_of_date,
                company=company, run_id=run_id, limits=limits,
                config_version=config_version, index_version=index_version), config=config)
        except KeyboardInterrupt:
            result = dict(graph.get_state(config).values)
            result.update(status='interrupted', termination_reason='사용자 중단; 마지막 체크포인트에서 재개 가능')
            recorder.record('execution', {'status': 'interrupted'})
        except Exception as exc:
            result = dict(graph.get_state(config).values)
            result.update(status='failed', termination_reason='그래프 실행 경계 오류: ' + type(exc).__name__)
            recorder.record('execution', {'status': 'failed', 'error_type': type(exc).__name__})

        try:
            # A late layout failure re-enters the existing graph with the SAME
            # attempt/step budget and a format verdict for this report revision.
            while result.get('report') and result['status'] == 'passed':
                report = result['report']
                with TemporaryDirectory(dir=run_dir) as directory:
                    staged = Path(directory)
                    pdf = render_evaluation_pdf(report, staged / 'report.pdf')
                    pages = len(PdfReader(str(pdf)).pages)
                    if pages > 10:
                        from skala_rag.models.orchestration import QualityItem
                        verdict = result['quality_result'].model_copy(deep=True)
                        verdict.items = [QualityItem(criterion='format', verdict='fail', target='F',
                            reason=f'최종 PDF {pages}쪽: 최대 10쪽 초과',
                            questions=[f'현재 {pages}쪽입니다. 목차·핵심 수치·근거·한계는 유지하고 중복 설명을 줄여 10쪽 이내로 축약하세요.'])
                            if item.criterion == 'format' else item for item in verdict.items]
                        recorder.record('publication', {'status': 'rework', 'pages': pages,
                            'report_revision': result['report_revision']})
                        graph.update_state(config, {'status': 'running', 'termination_reason': None,
                            'quality_result': verdict}, as_node='collect')
                        result = invoke_supervisor(graph, None, config=config)
                        continue
                    (staged / 'report.md').write_text(render_evaluation_markdown(report), encoding='utf-8')
                    if not args.no_pdf:
                        pdf.replace(run_dir / 'report.pdf')
                    (staged / 'report.md').replace(run_dir / 'report.md')
                    break
        except KeyboardInterrupt:
            result = dict(graph.get_state(config).values)
            result.update(status='interrupted', termination_reason='최종 발행·축약 중 사용자 중단')
        except Exception as exc:
            result = dict(graph.get_state(config).values)
            result.update(status='failed', termination_reason='최종 발행·축약 오류: ' + type(exc).__name__)
            recorder.record('storage', {'status': 'failed', 'error_type': type(exc).__name__})
    if result['status'] != 'passed':
        for name in ('report.md', 'report.pdf'):
            (run_dir / name).unlink(missing_ok=True)
    recorder.finish(result['status'])
    payload = supervisor_storage_payload(result)
    payload['tracing'] = {'project': recorder.project, 'trace_id': run_id,
                          'delivery_status': recorder.delivery_status}
    (run_dir / 'result.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{run_id}: {result["status"]} → {run_dir}')
    if result['status'] != 'passed':
        print('최종 보고서 미발행 사유: ' + (result.get('termination_reason') or '실행 결과 확인 필요'))
        quality = result.get('quality_result')
        if quality:
            for item in quality.items:
                if item.verdict != 'pass':
                    print(f'  {item.criterion}: {item.verdict} - {item.reason}')
        for error in result.get('task_errors', {}).values():
            print(f'  작업 {error.node}: {error.type} - {error.message}')
        print(f'상세 결과: {run_dir / "result.json"}')
    if recorder.remote_errors:
        print('LangSmith 전송 실패: events.jsonl의 tracing 오류를 확인하세요.')
    return 0 if result['status'] == 'passed' and not recorder.remote_errors else 2


def _parser(prog: str = 'skala-rag') -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog)
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser('analyze', help='Run A–F and save PDF, JSON and Markdown reports')
    analyze.add_argument('--query', required=True)
    analyze.add_argument('--company', action='append', default=[], help='Candidate company name; repeat for a batch')
    analyze.add_argument('--as-of-date', type=date.fromisoformat, default=date.today())
    analyze.add_argument('--research-root', type=Path)
    analyze.add_argument('--retriever', choices=['faiss', 'bm25'], default='faiss')
    analyze.add_argument('--index', type=Path, default=Path('storage/indexes/qwen3-0.6b-v1'))
    analyze.add_argument('--device', default='cpu', choices=['auto', 'cpu', 'mps', 'cuda'])
    analyze.add_argument('--model', help='Optional LangChain OpenAI model name for generation and scoring')
    analyze.add_argument('--financial-api', action='store_true', help='Use configured DART/FSC/KIND credentials')
    analyze.add_argument('--output', type=Path, default=Path('storage/reports'))
    analyze.set_defaults(handler=_analyze_command)

    orchestrate = commands.add_parser('orchestrate', help='Supervisor research, neutral report, quality loop and tracing')
    orchestrate.add_argument('--query')
    orchestrate.add_argument('--company')
    orchestrate.add_argument('--as-of-date', type=date.fromisoformat)
    orchestrate.add_argument('--research-root', type=Path)
    orchestrate.add_argument('--storage-root', type=Path, help='Existing storage bundle with indexes, raw and models')
    orchestrate.add_argument('--retriever', choices=['faiss', 'bm25'],
                             help='Defaults to FAISS when an index exists, otherwise BM25')
    orchestrate.add_argument('--index', type=Path, help='Defaults to <storage-root>/indexes/qwen3-0.6b-v1')
    orchestrate.add_argument('--device', default='cpu', choices=['auto', 'cpu', 'mps', 'cuda'])
    orchestrate.add_argument('--model', help='Structured research/generation and Supervisor sufficiency model')
    orchestrate.add_argument('--judge-model', help='Separate semantic report Judge; defaults to --model')
    orchestrate.add_argument('--financial-api', action='store_true')
    orchestrate.add_argument('--output', type=Path, default=Path('storage/reports'))
    identity = orchestrate.add_mutually_exclusive_group()
    identity.add_argument('--run-id', help='New run UUID')
    identity.add_argument('--resume', help='Resume original run UUID with the same configuration')
    orchestrate.add_argument('--langsmith', action='store_true', help='Export redacted node spans; requires LANGSMITH_API_KEY')
    orchestrate.add_argument('--langsmith-project', default=None)
    orchestrate.add_argument('--no-pdf', action='store_true')
    orchestrate.add_argument('--max-attempts', type=int, default=4, help='Total research attempts including the initial call (4 = initial + 3 re-investigations)')
    orchestrate.add_argument('--max-report-attempts', type=int, default=2)
    orchestrate.add_argument('--max-errors', type=int, default=4)
    orchestrate.add_argument('--max-steps', type=int, default=80)
    orchestrate.add_argument('--max-supervisor-steps', type=int, default=20)
    orchestrate.set_defaults(handler=_orchestrate_command)

    report = commands.add_parser('report', help='Render a saved analysis JSON to PDF or Markdown')
    report.add_argument('--input', type=Path, required=True)
    report.add_argument('--output', type=Path, required=True)
    report.set_defaults(handler=_report_command)
    index = commands.add_parser("index", help="Build or query a local FAISS index")
    index_commands = index.add_subparsers(dest="index_command", required=True)

    build = index_commands.add_parser("build", help="Embed a research directory")
    build.add_argument("--source", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--version", default="qwen3-embedding-0.6b-v1")
    build.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    build.add_argument("--batch-size", type=int, default=8)
    build.add_argument("--target-tokens", type=int, default=500)
    build.add_argument("--max-tokens", type=int, default=900)
    build.add_argument("--overlap-tokens", type=int, default=80)
    build.set_defaults(handler=_build_command)

    search = index_commands.add_parser("search", help="Search an existing index")
    search.add_argument("--index", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--company-id")
    search.add_argument("--source-grade", action="append", default=[])
    search.add_argument("--dimension", action="append", default=[])
    search.add_argument("--instruction")
    search.add_argument("--top-k", type=int, default=10)
    search.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    search.set_defaults(handler=_search_command)
    return parser


def main(argv: list[str] | None = None, *, prog: str = 'skala-rag') -> int:
    args = _parser(prog).parse_args(argv)
    try:
        return args.handler(args)
    except (ValueError, FileNotFoundError, ImportError) as exc:
        import sys
        print(f'Error: {exc}', file=sys.stderr)
        if isinstance(exc, ImportError):
            print('현재 Python에 의존성이 없습니다. uv sync --extra llm --group dev 후 '
                  'uv run python app.py로 실행하세요.', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
