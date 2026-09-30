from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from skala_rag.ingestion import DocumentChunker, EvidenceIndexBuilder
from skala_rag.retrieval import FaissEvidenceRetriever, RetrievalQuery


class WordTokenizer:
    def encode(self, text: str, *, add_special_tokens: bool = False) -> list[int]:
        return [
            int(hashlib.sha256(word.encode()).hexdigest()[:8], 16)
            for word in text.split()
        ]

    def decode(
        self, token_ids: list[int], *, skip_special_tokens: bool = True
    ) -> str:
        return " ".join(str(value) for value in token_ids)


class FakeEmbedder:
    model_name = "fake-embedding"
    dimension = 32
    query_prompt_version = "test-v1"

    def __init__(self) -> None:
        self.tokenizer = WordTokenizer()

    def _embed(self, texts: list[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dimension), dtype="float32")
        for row, text in enumerate(texts):
            for word in text.lower().split():
                column = int(hashlib.sha256(word.encode()).hexdigest()[:8], 16)
                matrix[row, column % self.dimension] += 1
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.maximum(norms, 1e-12)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_query(
        self, query: str, *, instruction: str | None = None
    ) -> np.ndarray:
        return self._embed([query])


def test_build_save_load_and_filtered_search(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "01_로봇회사" / "A_핵심근거").mkdir(parents=True)
    (source / "02_다른회사" / "D_언론_시장_데모").mkdir(parents=True)
    (source / "01_로봇회사" / "A_핵심근거" / "battery.md").write_text(
        "# 제품\nrobot battery safety certification",
        encoding="utf-8",
    )
    (source / "02_다른회사" / "D_언론_시장_데모" / "market.md").write_text(
        "# 시장\nrobot delivery market growth",
        encoding="utf-8",
    )
    embedder = FakeEmbedder()
    output = tmp_path / "index-v1"
    manifest = EvidenceIndexBuilder(
        embedder,
        chunker=DocumentChunker(
            embedder.tokenizer,
            target_tokens=50,
            max_tokens=80,
            overlap_tokens=5,
        ),
    ).build(source, output, index_version="test-v1")

    assert manifest.document_count == 2
    assert manifest.chunk_count == 2
    assert (output / "evidence.faiss").is_file()
    assert (output / "metadata.sqlite3").is_file()

    retriever = FaissEvidenceRetriever(output, embedder)
    hits = retriever.search(
        RetrievalQuery(
            query="battery safety certification",
            company_id="company-01",
            source_grades=["A"],
            top_k=3,
        )
    )

    assert len(hits) == 1
    assert hits[0].company_name == "로봇회사"
    assert "battery" in hits[0].text

    # Path-based metadata joins must filter before applying top_k, even when
    # the requested candidate pool is smaller than the complete index.
    selected = retriever.search(RetrievalQuery(query='battery safety certification',
        source_paths=['02_다른회사/D_언론_시장_데모/market.md'], top_k=1, fetch_k=1))
    assert len(selected) == 1
    assert selected[0].company_id == 'company-02'


def test_retriever_rejects_tampered_index(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.md").write_text("robot evidence", encoding="utf-8")
    embedder = FakeEmbedder()
    output = tmp_path / "index-v1"
    EvidenceIndexBuilder(embedder).build(source, output, index_version="test-v1")
    with (output / "evidence.faiss").open("ab") as stream:
        stream.write(b"tampered")

    with pytest.raises(ValueError, match="checksum mismatch"):
        FaissEvidenceRetriever(output, embedder)
