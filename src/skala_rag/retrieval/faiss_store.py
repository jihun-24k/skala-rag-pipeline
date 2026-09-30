"""Small, explicit FAISS wrapper with stable int64 IDs."""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

import numpy as np


class FaissVectorStore:
    def __init__(
        self,
        dimension: int,
        *,
        index: Any | None = None,
    ) -> None:
        import faiss

        # On macOS, PyTorch and FAISS can load conflicting OpenMP runtimes in
        # one process. Multi-threaded FAISS search may then terminate with a
        # segmentation fault; one FAISS thread is stable for this local index.
        if platform.system() == "Darwin":
            faiss.omp_set_num_threads(1)
        self.dimension = dimension
        self._index = index or faiss.IndexIDMap2(faiss.IndexFlatIP(dimension))
        if self._index.d != dimension:
            raise ValueError(
                f"FAISS dimension {self._index.d} does not match {dimension}"
            )

    @property
    def size(self) -> int:
        return int(self._index.ntotal)

    def add(self, vectors: np.ndarray, vector_ids: np.ndarray) -> None:
        prepared_vectors = np.ascontiguousarray(vectors, dtype="float32")
        prepared_ids = np.ascontiguousarray(vector_ids, dtype="int64")
        if prepared_vectors.ndim != 2 or prepared_vectors.shape[1] != self.dimension:
            raise ValueError("Embedding matrix has an invalid dimension")
        if prepared_vectors.shape[0] != prepared_ids.shape[0]:
            raise ValueError("Vector and ID counts do not match")
        self._index.add_with_ids(prepared_vectors, prepared_ids)

    def search(self, query_vector: np.ndarray, top_k: int) -> tuple[np.ndarray, np.ndarray]:
        prepared = np.ascontiguousarray(query_vector, dtype="float32")
        if prepared.ndim != 2 or prepared.shape[1] != self.dimension:
            raise ValueError("Query embedding has an invalid dimension")
        return self._index.search(prepared, min(top_k, max(self.size, 1)))

    def save(self, path: Path) -> None:
        import faiss

        path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(path))

    @classmethod
    def load(cls, path: Path, *, dimension: int) -> "FaissVectorStore":
        import faiss

        return cls(dimension, index=faiss.read_index(str(path)))
