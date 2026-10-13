"""Injectable search contracts and bridges to agent-specific retrieval APIs."""
from __future__ import annotations

from datetime import date
from typing import Protocol
import unicodedata

from skala_rag.agents.market_competition.documents import MarketDocument
from skala_rag.agents.market_competition.retrieval import RetrievedChunk
from skala_rag.retrieval.models import RetrievalHit, RetrievalQuery


class EvidenceRetriever(Protocol):
    def search(self, request: RetrievalQuery) -> list[RetrievalHit]: ...


class MarketRetriever(Protocol):
    def search(self, query: str, *, scope: str, company_ids: set[str],
               forms: set[str], as_of_date: date, limit: int = 5) -> list[RetrievedChunk]: ...


class FaissMarketRetriever:
    """Join vectors to reviewed source metadata; never infer dates or original URLs.

    Old indexes use company-01 identifiers, while the catalog uses robros etc.
    The source path join resolves that mismatch without changing existing indexes.
    Unmatched chunks are excluded rather than given fabricated provenance.
    """

    def __init__(self, retriever: EvidenceRetriever, documents: list[MarketDocument],
                 *, fetch_k: int, augment_with_lexical: bool = False):
        self.retriever = retriever
        self.documents = documents
        self.fetch_k = fetch_k
        from skala_rag.agents.market_competition.retrieval import LocalMarketRetriever
        self.lexical = LocalMarketRetriever(documents) if augment_with_lexical else None

    def search(self, query: str, *, scope: str, company_ids: set[str],
               forms: set[str], as_of_date: date, limit: int = 5) -> list[RetrievedChunk]:
        eligible = [d for d in self.documents if d.scope == scope
                    and d.source_grade != 'E' and not d.future_plan
                    and d.observed_at <= as_of_date
                    and (d.published_at is None or d.published_at <= as_of_date)
                    and (bool(company_ids.intersection(d.company_ids)) if scope == 'company'
                         else bool(forms.intersection(d.forms)))]
        # Ask for the full ranked candidate pool before metadata filtering.
        paths = [d.locator for d in eligible if d.locator]
        if not paths:
            return []
        hits = self.retriever.search(RetrievalQuery(query=query, top_k=min(max(limit * 4, limit), 100),
                           source_paths=paths, fetch_k=self.fetch_k))
        result = []
        seen = set()
        for hit in hits:
            path = unicodedata.normalize('NFC', hit.source_path)
            for doc in eligible:
                locator = unicodedata.normalize('NFC', doc.locator or '')
                if not locator or not (path == locator or path.endswith('/' + locator)):
                    continue
                offset = doc.text.find(hit.text)
                if offset < 0:
                    # Chunking can normalize whitespace; use the verified source text.
                    text, offset = doc.text, 0
                else:
                    text = hit.text
                identity = (doc.document_id, text)
                if identity not in seen:
                    result.append(RetrievedChunk(hit.chunk_id, doc, text, offset, hit.score))
                    seen.add(identity)
                break
            if len(result) >= limit:
                break
        if self.lexical is not None:
            lexical = self.lexical.search(query, scope=scope, company_ids=company_ids,
                forms=forms, as_of_date=as_of_date, limit=limit)
            # Interleave verified source lanes so vector dominance cannot hide
            # exact product names. Preserve source metadata and bound context size.
            merged, seen_sources = [], set()
            for index in range(max(len(lexical), len(result))):
                for lane in (lexical, result):
                    if index < len(lane):
                        chunk = lane[index]
                        key = (chunk.document.document_id, chunk.offset)
                        if key not in seen_sources:
                            merged.append(chunk)
                            seen_sources.add(key)
            return merged[:limit]
        return result
