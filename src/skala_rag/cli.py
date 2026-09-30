"""Command-line entrypoint for local indexing and retrieval."""

from __future__ import annotations

import argparse
import json
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skala-rag")
    commands = parser.add_subparsers(dest="command", required=True)
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
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
