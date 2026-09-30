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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skala-rag")
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


def main() -> int:
    args = _parser().parse_args()
    try:
        return args.handler(args)
    except (ValueError, FileNotFoundError, ImportError) as exc:
        import sys
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
