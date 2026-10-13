"""Typed, source-linked research documents and existing Markdown inventory loader."""
from __future__ import annotations

import json
import hashlib
import calendar
import re
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from skala_rag.models.investment import DomainModel
from skala_rag.agents.market_classification.catalog import default_research_root


class MarketDocument(DomainModel):
    document_id: str = Field(min_length=1)
    title: str
    text: str = Field(min_length=1)
    source_url: str
    source_grade: Literal['A', 'B', 'C', 'D', 'E']
    source_type: str = 'research_summary'
    content_kind: Literal['research_summary', 'source_excerpt'] = 'research_summary'
    scope: Literal['company', 'industry']
    company_ids: list[str] = Field(default_factory=list)
    forms: list[str] = Field(default_factory=list, description='Taxonomy keys or exact form labels')
    published_at: date | None = Field(default=None, description='Exact publication date or conservative upper bound for a partial date')
    published_at_raw: str | None = None
    observed_at: date
    future_plan: bool = False
    locator: str | None = None
    independent: bool | None = None

    @field_validator('source_url')
    @classmethod
    def public_url(cls, value: str) -> str:
        url = urlsplit(value)
        if url.scheme not in {'http', 'https'} or not url.hostname:
            raise ValueError('A full original HTTP(S) source URL is required')
        return value

    @model_validator(mode='after')
    def require_scope(self):
        if self.scope == 'company' and not self.company_ids:
            raise ValueError('Company documents require confirmed company_ids')
        if self.scope == 'industry' and not self.forms:
            raise ValueError('Industry documents require applicable forms')
        return self


def publication_bound(value: str | None) -> date | None:
    """Use end of year/month for partial dates to avoid future-information leakage."""
    if not value:
        return None
    if re.fullmatch(r'\d{4}', value):
        return date(int(value), 12, 31)
    if re.fullmatch(r'\d{4}-\d{2}', value):
        year, month = map(int, value.split('-'))
        return date(year, month, calendar.monthrange(year, month)[1])
    return date.fromisoformat(value)


def load_documents(research_root: Path | None = None) -> list[MarketDocument]:
    """Read canonical MD once per source. Do not label summaries as original full text."""
    root = (research_root or default_research_root()).resolve()
    manifest = json.loads((root / 'data/source_manifest.json').read_text(encoding='utf-8'))
    docs = []
    for source in manifest['sources']:
        paths = source.get('canonical_paths', {})
        ids = list(paths)
        if source.get('company_id') and source['company_id'] not in ids:
            ids.append(source['company_id'])
        # Unscoped sources are not silently treated as shared industry reports.
        if not ids:
            continue
        text = source.get('summary', '')
        locator = None
        for relative in paths.values():
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError('Research path escapes research root')
            if path.is_file():
                text = path.read_text(encoding='utf-8')
                text = re.sub(r'\A---\s*\n.*?\n---\s*\n', '', text, count=1, flags=re.S)
                locator = relative
                break
        if not text.strip():
            continue
        docs.append(MarketDocument(
            document_id=source['id'], title=source['title'], text=text,
            source_url=source['uri'], source_grade=source['source_grade'],
            source_type=source.get('source_type', 'research_summary'),
            scope='company', company_ids=ids,
            published_at=publication_bound(source.get('published_at')),
            published_at_raw=source.get('published_at'),
            observed_at=source.get('observed_at') or manifest['as_of_date'],
            future_plan=bool(source.get('future')), locator=locator,
        ))
    # The storage bundle inventories papers/patents separately from source_manifest.
    # Join only verified local canonical files; index presence is not provenance.
    inventory = root / 'data/evidence_documents.jsonl'
    seen = {doc.document_id for doc in docs}
    if inventory.is_file():
        for line in inventory.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if item['doc_id'] in seen:
                continue
            relative = item['relative_path']
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError('Evidence inventory path escapes research root')
            raw = path.read_bytes()
            expected = item.get('content_sha256')
            if expected and hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError(f'Evidence inventory checksum mismatch: {relative}')
            text = re.sub(r'\A---\s*\n.*?\n---\s*\n', '', raw.decode('utf-8'), count=1, flags=re.S)
            docs.append(MarketDocument(document_id=item['doc_id'], title=item['title'], text=text,
                source_url=item.get('original_url') or item['source_url'],
                source_grade=item['source_grade'], source_type=item['document_type'],
                scope='company', company_ids=[item['company_id']],
                published_at=publication_bound(item.get('published_at')),
                published_at_raw=item.get('published_at'), observed_at=item['observed_at'],
                future_plan=bool(item.get('future')), locator=relative,
                independent=item.get('independent_verification')))
            seen.add(item['doc_id'])
    # Shared market reports and new company evidence use the same validated format.
    additional = root / 'data/market_documents.jsonl'
    if additional.exists():
        for line in additional.read_text(encoding='utf-8').splitlines():
            if line.strip():
                docs.append(MarketDocument.model_validate_json(line))
    return docs
