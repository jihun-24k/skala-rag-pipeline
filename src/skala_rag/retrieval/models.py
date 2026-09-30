"""Shared models for local vector indexing and retrieval."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class RetrievalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceDocument(RetrievalModel):
    document_id: str
    source_path: str
    locator: str | None = None
    title: str
    text: str
    content_hash: str
    company_id: str | None = None
    company_name: str | None = None
    source_type: str
    source_grade: str
    dimension: str


class DocumentChunk(RetrievalModel):
    vector_id: int
    chunk_id: str
    document_id: str
    source_path: str
    locator: str | None = None
    title: str
    text: str
    embedding_text: str
    content_hash: str
    token_count: int
    company_id: str | None = None
    company_name: str | None = None
    source_type: str
    source_grade: str
    dimension: str
    index_version: str


class RetrievalQuery(RetrievalModel):
    query: str
    company_id: str | None = None
    source_grades: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    source_paths: list[str] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=100)
    fetch_k: int | None = Field(default=None, ge=1)
    instruction: str | None = None


class RetrievalHit(RetrievalModel):
    vector_id: int
    score: float
    chunk_id: str
    document_id: str
    title: str
    text: str
    source_path: str
    locator: str | None = None
    company_id: str | None = None
    company_name: str | None = None
    source_type: str
    source_grade: str
    dimension: str


class IndexManifest(RetrievalModel):
    index_version: str
    created_at: datetime
    source_root: str
    embedding_model: str
    embedding_dimension: int
    normalized: bool
    metric: str
    index_type: str
    query_prompt_version: str
    document_count: int
    chunk_count: int
    skipped_duplicate_count: int
    files: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> "IndexManifest":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
