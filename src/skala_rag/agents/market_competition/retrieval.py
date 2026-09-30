"""Local BM25 retrieval with separate shared-industry/company evidence lanes."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from .documents import MarketDocument


def tokens(text: str) -> list[str]:
    words = re.findall(r'[a-z0-9]+|[가-힣]+', text.casefold())
    # Korean bigrams allow matching inflected words without extra morphology packages.
    return words + [w[i:i+2] for w in words if re.fullmatch(r'[가-힣]{3,}', w)
                    for i in range(len(w)-1)]


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document: MarketDocument
    text: str
    offset: int
    rank_score: float


class LocalMarketRetriever:
    def __init__(self, documents: Iterable[MarketDocument], chunk_size: int = 1200, overlap: int = 150):
        if chunk_size < 100 or not 0 <= overlap < chunk_size:
            raise ValueError('Require chunk_size >= 100 and 0 <= overlap < chunk_size')
        self.documents = list(documents)
        ids = [d.document_id for d in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate document_id')
        self._chunks = []
        for doc in self.documents:
            for start in range(0, len(doc.text), chunk_size-overlap):
                text = doc.text[start:start+chunk_size]
                self._chunks.append((doc, start, text, Counter(tokens(doc.title+' '+text))))
                if start + chunk_size >= len(doc.text):
                    break

    def search(self, query: str, *, scope: str, company_ids: set[str], forms: set[str],
               as_of_date: date, limit: int = 5) -> list[RetrievedChunk]:
        if limit <= 0:
            return []
        eligible = []
        for item in self._chunks:
            d = item[0]
            if d.scope != scope or d.source_grade == 'E' or d.future_plan:
                continue
            if d.observed_at > as_of_date or (d.published_at and d.published_at > as_of_date):
                continue
            if scope == 'company' and not company_ids.intersection(d.company_ids):
                continue
            if scope == 'industry' and not forms.intersection(d.forms):
                continue
            eligible.append(item)
        if not eligible:
            return []
        df = Counter(t for _, _, _, counts in eligible for t in counts)
        avg = sum(sum(x[3].values()) for x in eligible)/len(eligible)
        result = []
        for doc, offset, text, counts in eligible:
            length = sum(counts.values())
            score = 0.0
            for term in set(tokens(query)):
                freq = counts[term]
                if freq:
                    idf = math.log(1+(len(eligible)-df[term]+0.5)/(df[term]+0.5))
                    score += idf*freq*2.5/(freq+1.5*(0.25+0.75*length/max(avg, 1)))
            if score > 0:
                result.append(RetrievedChunk(f'{doc.document_id}#char={offset}', doc, text, offset, score))
        return sorted(result, key=lambda c: (-c.rank_score, c.chunk_id))[:limit]
