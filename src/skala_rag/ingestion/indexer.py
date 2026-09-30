"""Build a versioned FAISS index and its SQLite metadata atomically."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from skala_rag.ingestion.chunker import DocumentChunker
from skala_rag.ingestion.embedder import QwenEmbeddingProvider
from skala_rag.ingestion.loader import ResearchDocumentLoader
from skala_rag.retrieval.faiss_store import FaissVectorStore
from skala_rag.retrieval.metadata_repository import ChunkMetadataRepository
from skala_rag.retrieval.models import IndexManifest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class EvidenceIndexBuilder:
    def __init__(
        self,
        embedder: QwenEmbeddingProvider,
        *,
        loader: ResearchDocumentLoader | None = None,
        chunker: DocumentChunker | None = None,
    ) -> None:
        self._embedder = embedder
        self._loader = loader or ResearchDocumentLoader()
        self._chunker = chunker or DocumentChunker(embedder.tokenizer)

    def build(
        self,
        source_root: Path,
        output_dir: Path,
        *,
        index_version: str,
    ) -> IndexManifest:
        source_root = source_root.resolve()
        output_dir = output_dir.resolve()
        if output_dir.exists():
            raise FileExistsError(
                f"Index directory already exists; choose a new version: {output_dir}"
            )
        if not source_root.is_dir():
            raise NotADirectoryError(source_root)

        documents = list(self._loader.iter_documents(source_root))
        chunks, skipped_duplicates = self._chunker.chunk_documents(
            documents,
            index_version=index_version,
        )
        if not chunks:
            raise ValueError("No indexable chunks were produced")

        output_dir.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(
            tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent)
        )
        try:
            vectors = self._embedder.embed_documents(
                [chunk.embedding_text for chunk in chunks]
            )
            if vectors.shape != (len(chunks), self._embedder.dimension):
                raise ValueError(
                    f"Unexpected embedding matrix shape: {vectors.shape}"
                )

            vector_store = FaissVectorStore(self._embedder.dimension)
            vector_store.add(
                vectors,
                np.asarray([chunk.vector_id for chunk in chunks], dtype="int64"),
            )
            index_path = temp_dir / "evidence.faiss"
            vector_store.save(index_path)

            metadata_path = temp_dir / "metadata.sqlite3"
            repository = ChunkMetadataRepository(metadata_path)
            repository.initialize()
            repository.insert_chunks(chunks)
            if repository.count() != vector_store.size:
                raise ValueError("FAISS and SQLite record counts do not match")

            manifest = IndexManifest(
                index_version=index_version,
                created_at=datetime.now(timezone.utc),
                source_root=str(source_root),
                embedding_model=self._embedder.model_name,
                embedding_dimension=self._embedder.dimension,
                normalized=True,
                metric="inner_product",
                index_type="IDMap2,Flat",
                query_prompt_version=self._embedder.query_prompt_version,
                document_count=len(documents),
                chunk_count=len(chunks),
                skipped_duplicate_count=skipped_duplicates,
                files={
                    "evidence.faiss": _sha256_file(index_path),
                    "metadata.sqlite3": _sha256_file(metadata_path),
                },
            )
            (temp_dir / "manifest.json").write_text(
                manifest.model_dump_json(indent=2),
                encoding="utf-8",
            )
            temp_dir.replace(output_dir)
            return manifest
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
