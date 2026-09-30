"""Load research documents while treating their contents strictly as data."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from skala_rag.retrieval.models import SourceDocument

_SUPPORTED_SUFFIXES = {".md", ".json", ".jsonl", ".pdf"}
_SKIPPED_PARTS = {"__MACOSX", "_archive", "scripts", "__pycache__"}
_COMPANY_PATTERN = re.compile(r"^(\d{2})_(.+)$")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _infer_company(parts: tuple[str, ...]) -> tuple[str | None, str | None]:
    for part in parts:
        match = _COMPANY_PATTERN.match(_normalized(part))
        if match:
            number, name = match.groups()
            return f"company-{number}", name.replace("_", " ")
    return None, None


def _infer_source_grade(parts: tuple[str, ...]) -> str:
    normalized_parts = [_normalized(part) for part in parts]
    for grade in ("A", "B", "C", "D", "E"):
        if any(part.startswith(f"{grade}_") for part in normalized_parts):
            return grade
    if any("특허" in part or "논문" in part for part in normalized_parts):
        return "A"
    return "D"


def _infer_source_type(parts: tuple[str, ...], suffix: str) -> str:
    joined = "/".join(_normalized(part) for part in parts)
    if "특허" in joined:
        return "patent"
    if "논문" in joined:
        return "academic"
    if "공공자료" in joined or "공시" in joined:
        return "regulatory"
    if "회사발표" in joined:
        return "first_party"
    if "언론" in joined or "시장" in joined or "데모" in joined:
        return "independent_media"
    if suffix == ".pdf":
        return "pdf"
    return "research_note"


def _infer_dimension(parts: tuple[str, ...]) -> str:
    joined = "/".join(_normalized(part) for part in parts)
    rules = (
        ("특허", "patent"),
        ("논문", "technology"),
        ("재무", "financial"),
        ("투자", "funding"),
        ("시장", "market"),
        ("경쟁", "competition"),
        ("제품", "product"),
        ("회사발표", "company"),
    )
    return next((dimension for keyword, dimension in rules if keyword in joined), "general")


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


class ResearchDocumentLoader:
    """Read supported files without executing code from the source archive."""

    def iter_documents(self, source_root: Path) -> Iterator[SourceDocument]:
        root = source_root.resolve()
        for path in sorted(root.rglob("*"), key=lambda item: str(item)):
            if not path.is_file() or path.suffix.lower() not in _SUPPORTED_SUFFIXES:
                continue
            relative = path.relative_to(root)
            if any(part in _SKIPPED_PARTS for part in relative.parts):
                continue
            if any(part.startswith("._") for part in relative.parts):
                continue

            suffix = path.suffix.lower()
            if suffix == ".md":
                yield self._build_document(root, path, self._read_text(path))
            elif suffix == ".json":
                value = json.loads(self._read_text(path))
                yield self._build_document(root, path, _json_text(value))
            elif suffix == ".jsonl":
                for line_number, line in enumerate(
                    self._read_text(path).splitlines(), start=1
                ):
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    yield self._build_document(
                        root,
                        path,
                        _json_text(value),
                        locator=f"line:{line_number}",
                    )
            elif suffix == ".pdf":
                yield from self._read_pdf(root, path)

    @staticmethod
    def _read_text(path: Path) -> str:
        return path.read_text(encoding="utf-8-sig", errors="replace")

    def _read_pdf(self, root: Path, path: Path) -> Iterator[SourceDocument]:
        from pypdf import PdfReader

        reader = PdfReader(path)
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                yield self._build_document(
                    root,
                    path,
                    text,
                    locator=f"page:{page_number}",
                )

    def _build_document(
        self,
        root: Path,
        path: Path,
        text: str,
        locator: str | None = None,
    ) -> SourceDocument:
        relative = path.relative_to(root)
        normalized_parts = tuple(_normalized(part) for part in relative.parts)
        normalized_path = "/".join(normalized_parts)
        # Company IDs are encoded in directory names (for example,
        # ``01_로브로스``). A data filename may also start with ``00_`` and
        # must not be mistaken for a company directory.
        company_id, company_name = _infer_company(normalized_parts[:-1])
        stripped = text.strip()
        content_hash = _sha256_text(stripped)
        document_key = f"{normalized_path}:{locator or ''}:{content_hash}"
        return SourceDocument(
            document_id=f"DOC-{_sha256_text(document_key)[:20]}",
            source_path=normalized_path,
            locator=locator,
            title=_normalized(path.stem),
            text=stripped,
            content_hash=content_hash,
            company_id=company_id,
            company_name=company_name,
            source_type=_infer_source_type(normalized_parts, path.suffix.lower()),
            source_grade=_infer_source_grade(normalized_parts),
            dimension=_infer_dimension(normalized_parts),
        )
