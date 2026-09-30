"""Local FAISS retrieval primitives."""

from skala_rag.retrieval.faiss_store import FaissVectorStore
from skala_rag.retrieval.models import (
    DocumentChunk,
    IndexManifest,
    RetrievalHit,
    RetrievalQuery,
    SourceDocument,
)
from skala_rag.retrieval.service import FaissEvidenceRetriever

__all__ = [
    "DocumentChunk",
    "FaissEvidenceRetriever",
    "FaissVectorStore",
    "IndexManifest",
    "RetrievalHit",
    "RetrievalQuery",
    "SourceDocument",
]
