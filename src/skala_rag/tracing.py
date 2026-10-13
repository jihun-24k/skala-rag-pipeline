"""Bounded, redacted orchestration events; opt-in synchronous LangSmith export."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

from skala_rag.models.orchestration import utc_now


def safe_text(value: str) -> str:
    value = re.sub(r'(?i)(authorization\s*[:=]\s*)(?:bearer|basic)\s+\S+',
                   r'\1[REDACTED]', value)
    value = re.sub(r'(?i)(api[_-]?key|token|authorization|password)\s*[:=]\s*\S+', r'\1=[REDACTED]', value)
    return re.sub(r'\b(?:sk-|lsv2_)[A-Za-z0-9_-]+', '[REDACTED]', value)[:500]


def _redact(value):
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, dict):
        return {key: '[REDACTED]' if re.search(r'(?i)api[_-]?key|token|authorization|password', key)
                else _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class TraceRecorder:
    def __init__(self, run_id: str, path: Path | None = None, *, enabled: bool = False,
                 project: str | None = None, client=None):
        UUID(run_id)
        self.run_id, self.path = run_id, path
        self.project = project or os.environ.get('LANGSMITH_PROJECT', 'skala-supervisor')
        self.client = client
        self.enabled = enabled
        self.remote_errors: list[str] = []
        self.lock = Lock()
        self.root_order = utc_now().strftime('%Y%m%dT%H%M%S%fZ') + run_id
        if enabled and client is None:
            if not os.environ.get('LANGSMITH_API_KEY'):
                raise ValueError('LANGSMITH_API_KEY is required when tracing is enabled')
            from langsmith import Client
            self.client = Client(auto_batch_tracing=False)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def _local(self, event):
        if self.path:
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + '\n')

    def start(self, *, resume=False):
        if not self.enabled:
            return
        try:
            if resume:
                try:
                    existing = self.client.read_run(self.run_id)
                    self.root_order = existing.dotted_order
                    return
                except Exception as exc:
                    if type(exc).__name__ != 'LangSmithNotFoundError':
                        raise
            self.client.create_run('physical-ai-supervisor', inputs={'run_id': self.run_id},
                run_type='chain', id=self.run_id, trace_id=self.run_id,
                dotted_order=self.root_order, project_name=self.project, start_time=utc_now())
        except Exception as exc:
            self._remote_error(exc)

    def _remote_error(self, exc):
        code = type(exc).__name__
        self.remote_errors.append(code)
        self._local({'run_id': self.run_id, 'node': 'tracing', 'status': 'failed',
                     'error_type': code, 'ts': utc_now().isoformat()})

    def record(self, node: str, data: dict, *, started_at=None):
        # Callers supply only control metadata/IDs, never State or prompts.
        event = _redact(data)
        event.update(run_id=self.run_id, node=node, ts=utc_now().isoformat())
        with self.lock:
            self._local(event)
            if self.enabled:
                try:
                    event_id = str(uuid4())
                    timestamp = started_at or utc_now()
                    self.client.create_run(node, inputs={'run_id': self.run_id}, outputs=event,
                        run_type='chain', id=event_id, parent_run_id=self.run_id,
                        trace_id=self.run_id, project_name=self.project,
                        dotted_order=self.root_order + '.' + timestamp.strftime('%Y%m%dT%H%M%S%fZ') + event_id,
                        start_time=timestamp, end_time=utc_now())
                except Exception as exc:
                    self._remote_error(exc)

    def finish(self, status: str):
        if self.enabled:
            try:
                self.client.update_run(self.run_id, outputs={'status': status}, end_time=utc_now())
                self.client.flush()
            except Exception as exc:
                self._remote_error(exc)

    @property
    def delivery_status(self) -> str:
        return 'disabled' if not self.enabled else 'failed' if self.remote_errors else 'submitted'
