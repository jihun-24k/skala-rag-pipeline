"""Qwen3 embedding adapter for documents and instructed queries."""

from __future__ import annotations

from typing import Any

import numpy as np

DEFAULT_QUERY_INSTRUCTION = (
    "Given a Korean investment due diligence query, retrieve relevant evidence "
    "about a Physical AI company"
)


class QwenEmbeddingProvider:
    model_name = "Qwen/Qwen3-Embedding-0.6B"
    dimension = 1024
    query_prompt_version = "physical-ai-due-diligence-v1"

    def __init__(
        self,
        *,
        device: str | None = None,
        batch_size: int = 16,
        max_length: int = 1024,
        model: Any | None = None,
    ) -> None:
        if model is None:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(self.model_name, device=device)
        self._model = model
        self._model.max_seq_length = max_length
        self._batch_size = batch_size

    @property
    def tokenizer(self) -> Any:
        return self._model.tokenizer

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=True,
        )
        return np.asarray(vectors, dtype="float32")

    def embed_query(
        self,
        query: str,
        *,
        instruction: str | None = None,
    ) -> np.ndarray:
        task = instruction or DEFAULT_QUERY_INSTRUCTION
        prompted = f"Instruct: {task}\nQuery: {query}"
        vector = self._model.encode(
            [prompted],
            batch_size=1,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vector, dtype="float32")
