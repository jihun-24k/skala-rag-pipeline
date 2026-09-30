from pathlib import Path

from skala_rag.ingestion.chunker import DocumentChunker
from skala_rag.ingestion.loader import ResearchDocumentLoader


class CharacterTokenizer:
    def encode(self, text: str, *, add_special_tokens: bool = False) -> list[int]:
        return [ord(character) for character in text]

    def decode(
        self, token_ids: list[int], *, skip_special_tokens: bool = True
    ) -> str:
        return "".join(chr(value) for value in token_ids)


def test_loader_reads_supported_data_and_infers_company(tmp_path: Path) -> None:
    company_dir = tmp_path / "01_로브로스" / "A_핵심근거" / "논문"
    company_dir.mkdir(parents=True)
    (company_dir / "paper.md").write_text("# 기술\n로봇 제어 기술", encoding="utf-8")
    (company_dir / "records.jsonl").write_text(
        '{"title":"첫 번째"}\n{"title":"두 번째"}\n', encoding="utf-8"
    )
    skipped = tmp_path / "scripts"
    skipped.mkdir()
    (skipped / "ignore.py").write_text("raise RuntimeError()", encoding="utf-8")

    documents = list(ResearchDocumentLoader().iter_documents(tmp_path))

    assert len(documents) == 3
    assert {document.company_id for document in documents} == {"company-01"}
    assert {document.source_grade for document in documents} == {"A"}
    assert {document.source_type for document in documents} == {"academic"}
    assert {document.locator for document in documents if document.locator} == {
        "line:1",
        "line:2",
    }


def test_loader_does_not_infer_company_from_filename(tmp_path: Path) -> None:
    path = tmp_path / "00_공통자료.md"
    path.write_text("공통 시장 자료", encoding="utf-8")

    [document] = list(ResearchDocumentLoader().iter_documents(tmp_path))

    assert document.company_id is None
    assert document.company_name is None


def test_chunker_uses_overlap_and_removes_duplicate_content() -> None:
    loader = ResearchDocumentLoader()
    tokenizer = CharacterTokenizer()
    document = loader._build_document(
        Path("/tmp"),
        Path("/tmp/01_회사/report.md"),
        "# 시장\n" + "가" * 120,
    )
    duplicate = document.model_copy(update={"document_id": "DOC-DUPLICATE"})
    chunker = DocumentChunker(
        tokenizer,
        target_tokens=40,
        max_tokens=50,
        overlap_tokens=10,
        min_tokens=5,
    )

    chunks, duplicate_count = chunker.chunk_documents(
        [document, duplicate],
        index_version="test-v1",
    )

    assert len(chunks) >= 3
    assert duplicate_count >= len(chunks)
    assert len({chunk.content_hash for chunk in chunks}) == len(chunks)
    assert all(chunk.token_count <= 50 for chunk in chunks)
    assert all(chunk.embedding_text.startswith("제목: report") for chunk in chunks)
