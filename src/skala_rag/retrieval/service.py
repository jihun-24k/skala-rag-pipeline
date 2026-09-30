"""Metadata-aware evidence retrieval over a read-only FAISS index."""

from __future__ import annotations

import hashlib
import unicodedata
from pathlib import Path
from typing import Protocol

from skala_rag.retrieval.faiss_store import FaissVectorStore
from skala_rag.retrieval.metadata_repository import ChunkMetadataRepository
from skala_rag.retrieval.models import IndexManifest, RetrievalHit, RetrievalQuery


class QueryEmbedder(Protocol):
    def embed_query(self, query: str, *, instruction: str | None = None): ...


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class FaissEvidenceRetriever:
    def __init__(
        self,
        index_dir: Path,
        embedder: QueryEmbedder,
        *,
        verify_checksums: bool = True,
    ) -> None:
        self.index_dir = index_dir
        self.manifest = IndexManifest.load(index_dir / "manifest.json")
        self._index_path = index_dir / "evidence.faiss"
        self._metadata_path = index_dir / "metadata.sqlite3"
        if verify_checksums:
            self._verify_file("evidence.faiss", self._index_path)
            self._verify_file("metadata.sqlite3", self._metadata_path)
        self._store = FaissVectorStore.load(
            self._index_path,
            dimension=self.manifest.embedding_dimension,
        )
        self._repository = ChunkMetadataRepository(self._metadata_path)
        self._embedder = embedder

    def _verify_file(self, name: str, path: Path) -> None:
        expected = self.manifest.files.get(name)
        if not expected or _sha256_file(path) != expected:
            raise ValueError(f"Index artifact checksum mismatch: {name}")

    def search(self, request: RetrievalQuery) -> list[RetrievalHit]:
        query_vector = self._embedder.embed_query(
            request.query,
            instruction=request.instruction,
        )
        filtered = request.company_id or request.source_grades or request.dimensions or request.source_paths
        fetch_k = (self.manifest.chunk_count if filtered else
                   request.fetch_k or max(request.top_k * 10, 50))
        scores, ids = self._store.search(query_vector, fetch_k)
        ordered_ids = [int(value) for value in ids[0] if int(value) >= 0]
        rows = self._repository.find_by_vector_ids(ordered_ids)

        hits: list[RetrievalHit] = []
        for score, vector_id in zip(scores[0], ids[0], strict=True):
            vector_id = int(vector_id)
            row = rows.get(vector_id)
            if row is None:
                continue
            if request.company_id and row["company_id"] != request.company_id:
                continue
            if request.source_grades and row["source_grade"] not in request.source_grades:
                continue
            if request.dimensions and row["dimension"] not in request.dimensions:
                continue
            path = unicodedata.normalize('NFC', row['source_path'])
            if request.source_paths and not any(
                path == p or path.endswith('/' + p)
                for p in (unicodedata.normalize('NFC', s) for s in request.source_paths)
            ):
                continue
            hits.append(
                RetrievalHit(
                    vector_id=vector_id,
                    score=float(score),
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    title=row["title"],
                    text=row["chunk_text"],
                    source_path=row["source_path"],
                    locator=row["locator"],
                    company_id=row["company_id"],
                    company_name=row["company_name"],
                    source_type=row["source_type"],
                    source_grade=row["source_grade"],
                    dimension=row["dimension"],
                )
            )
            if len(hits) >= request.top_k:
                break
        return hits
