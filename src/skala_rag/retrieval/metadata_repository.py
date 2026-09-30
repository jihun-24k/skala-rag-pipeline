"""SQLite metadata mapped to FAISS vector IDs."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from skala_rag.retrieval.models import DocumentChunk

_SCHEMA = """
CREATE TABLE IF NOT EXISTS document_chunks (
    vector_id INTEGER PRIMARY KEY,
    chunk_id TEXT NOT NULL UNIQUE,
    document_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    locator TEXT,
    title TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    company_id TEXT,
    company_name TEXT,
    source_type TEXT NOT NULL,
    source_grade TEXT NOT NULL,
    dimension TEXT NOT NULL,
    index_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_company ON document_chunks(company_id);
CREATE INDEX IF NOT EXISTS idx_chunks_dimension ON document_chunks(dimension);
CREATE INDEX IF NOT EXISTS idx_chunks_grade ON document_chunks(source_grade);
"""


class ChunkMetadataRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(_SCHEMA)

    def insert_chunks(self, chunks: Iterable[DocumentChunk]) -> None:
        rows = [
            (
                chunk.vector_id,
                chunk.chunk_id,
                chunk.document_id,
                chunk.source_path,
                chunk.locator,
                chunk.title,
                chunk.text,
                chunk.content_hash,
                chunk.token_count,
                chunk.company_id,
                chunk.company_name,
                chunk.source_type,
                chunk.source_grade,
                chunk.dimension,
                chunk.index_version,
            )
            for chunk in chunks
        ]
        with sqlite3.connect(self.path) as connection:
            connection.executemany(
                """
                INSERT INTO document_chunks (
                    vector_id, chunk_id, document_id, source_path, locator,
                    title, chunk_text, content_hash, token_count, company_id,
                    company_name, source_type, source_grade, dimension,
                    index_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def find_by_vector_ids(self, vector_ids: list[int]) -> dict[int, sqlite3.Row]:
        valid_ids = [value for value in vector_ids if value >= 0]
        if not valid_ids:
            return {}
        placeholders = ",".join("?" for _ in valid_ids)
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"SELECT * FROM document_chunks WHERE vector_id IN ({placeholders})",
                valid_ids,
            ).fetchall()
        return {int(row["vector_id"]): row for row in rows}

    def count(self) -> int:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT COUNT(*) FROM document_chunks").fetchone()
        return int(row[0]) if row else 0
