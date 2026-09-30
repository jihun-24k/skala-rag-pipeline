"""Token-aware chunking that preserves Markdown section context."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Protocol

from skala_rag.retrieval.models import DocumentChunk, SourceDocument

_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")


class Tokenizer(Protocol):
    def encode(
        self,
        text: str,
        *,
        add_special_tokens: bool = False,
        **kwargs: object,
    ) -> list[int]: ...

    def decode(self, token_ids: list[int], *, skip_special_tokens: bool = True) -> str: ...


class DocumentChunker:
    def __init__(
        self,
        tokenizer: Tokenizer,
        *,
        target_tokens: int = 500,
        max_tokens: int = 900,
        overlap_tokens: int = 80,
        min_tokens: int = 30,
    ) -> None:
        if not 0 <= overlap_tokens < target_tokens <= max_tokens:
            raise ValueError("Require 0 <= overlap < target <= max")
        self._tokenizer = tokenizer
        self._target_tokens = target_tokens
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens
        self._min_tokens = min_tokens

    def chunk_documents(
        self,
        documents: Iterable[SourceDocument],
        *,
        index_version: str,
    ) -> tuple[list[DocumentChunk], int]:
        chunks: list[DocumentChunk] = []
        seen_hashes: set[str] = set()
        skipped_duplicates = 0

        for document in documents:
            for text in self._chunk_text(document.text):
                content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                dedupe_key = f"{document.company_id or ''}:{content_hash}"
                if dedupe_key in seen_hashes:
                    skipped_duplicates += 1
                    continue
                seen_hashes.add(dedupe_key)
                vector_id = len(chunks) + 1
                chunk_id = f"CHK-{hashlib.sha256(f'{document.document_id}:{vector_id}:{content_hash}'.encode()).hexdigest()[:20]}"
                prefix = [f"제목: {document.title}"]
                if document.company_name:
                    prefix.append(f"기업: {document.company_name}")
                prefix.extend(
                    [
                        f"자료유형: {document.source_type}",
                        f"분석차원: {document.dimension}",
                    ]
                )
                embedding_text = "\n".join([*prefix, "", text])
                chunks.append(
                    DocumentChunk(
                        vector_id=vector_id,
                        chunk_id=chunk_id,
                        document_id=document.document_id,
                        source_path=document.source_path,
                        locator=document.locator,
                        title=document.title,
                        text=text,
                        embedding_text=embedding_text,
                        content_hash=content_hash,
                        token_count=self.count_tokens(text),
                        company_id=document.company_id,
                        company_name=document.company_name,
                        source_type=document.source_type,
                        source_grade=document.source_grade,
                        dimension=document.dimension,
                        index_version=index_version,
                    )
                )
        return chunks, skipped_duplicates

    def count_tokens(self, text: str) -> int:
        return len(self._encode(text))

    def _encode(self, text: str) -> list[int]:
        """Tokenize without emitting model-length warnings during pre-splitting."""
        try:
            return self._tokenizer.encode(
                text,
                add_special_tokens=False,
                verbose=False,
            )
        except TypeError:
            # Small test/dummy tokenizers need not implement Hugging Face kwargs.
            return self._tokenizer.encode(text, add_special_tokens=False)

    def _chunk_text(self, text: str) -> list[str]:
        blocks = self._markdown_blocks(text)
        chunks: list[str] = []
        current = ""

        for block in blocks:
            for fragment in self._split_oversized(block):
                candidate = f"{current}\n\n{fragment}".strip() if current else fragment
                if current and self.count_tokens(candidate) > self._target_tokens:
                    chunks.append(current.strip())
                    seeded = self._overlap_seed(current, fragment)
                    current = (
                        fragment
                        if self.count_tokens(seeded) > self._max_tokens
                        else seeded
                    )
                else:
                    current = candidate

                if self.count_tokens(current) >= self._max_tokens:
                    chunks.append(current.strip())
                    current = self._overlap_seed(current, "")

        if current.strip():
            if chunks and self.count_tokens(current) < self._min_tokens:
                merged = f"{chunks[-1]}\n\n{current}".strip()
                if self.count_tokens(merged) <= self._max_tokens:
                    chunks[-1] = merged
                else:
                    chunks.append(current.strip())
            else:
                chunks.append(current.strip())
        return [chunk for chunk in chunks if chunk]

    def _markdown_blocks(self, text: str) -> list[str]:
        blocks: list[str] = []
        headings: list[str] = []
        paragraph: list[str] = []

        def flush() -> None:
            if not paragraph:
                return
            body = "\n".join(paragraph).strip()
            paragraph.clear()
            if body:
                context = " > ".join(headings)
                blocks.append(f"섹션: {context}\n{body}" if context else body)

        for line in text.splitlines():
            match = _HEADING.match(line.strip())
            if match:
                flush()
                level = len(match.group(1))
                headings[:] = headings[: level - 1]
                headings.append(match.group(2).strip())
            elif line.strip():
                paragraph.append(line.rstrip())
            else:
                flush()
        flush()
        return blocks or [text.strip()]

    def _split_oversized(self, block: str) -> list[str]:
        token_ids = self._encode(block)
        if len(token_ids) <= self._max_tokens:
            return [block]
        step = self._max_tokens - self._overlap_tokens
        return [
            self._tokenizer.decode(
                token_ids[start : start + self._max_tokens],
                skip_special_tokens=True,
            ).strip()
            for start in range(0, len(token_ids), step)
            if token_ids[start : start + self._max_tokens]
        ]

    def _overlap_seed(self, previous: str, next_fragment: str) -> str:
        if self._overlap_tokens == 0:
            return next_fragment
        previous_ids = self._encode(previous)
        overlap = self._tokenizer.decode(
            previous_ids[-self._overlap_tokens :],
            skip_special_tokens=True,
        ).strip()
        return f"{overlap}\n\n{next_fragment}".strip()
