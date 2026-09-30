"""Read-only company master adapter. Replace with a PostgreSQL repository later."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol


class CompanyCatalog(Protocol):
    def list_companies(self) -> list[dict[str, Any]]: ...

    def get_company(self, company_id: str) -> dict[str, Any] | None: ...

    def source_url(self, source_id: str) -> str | None: ...

    @property
    def as_of_date(self) -> str: ...


def default_research_root() -> Path:
    """Find the adjacent research folder without embedding a user's home path."""

    override = os.getenv("SKALA_RESEARCH_ROOT")
    if override:
        root = Path(override).expanduser().resolve()
        if (root / "data/company_master.json").is_file():
            return root
        raise FileNotFoundError(f"Company master missing below SKALA_RESEARCH_ROOT: {root}")

    here = Path(__file__).resolve()
    for parent in here.parents:
        for root in parent.iterdir():
            if (root / "data/company_master.json").is_file():
                return root
    raise FileNotFoundError(
        "Company master not found; set SKALA_RESEARCH_ROOT to the 자료조사 directory"
    )


class JsonCompanyCatalog:
    """Snapshot of the reviewed research inventory, never a live web lookup."""

    def __init__(self, research_root: Path | None = None):
        self.root = (research_root or default_research_root()).resolve()
        data = self.root / "data"
        master = json.loads((data / "company_master.json").read_text(encoding="utf-8"))
        manifest = json.loads((data / "source_manifest.json").read_text(encoding="utf-8"))
        self._as_of_date: str = master["as_of_date"]
        self._companies: list[dict[str, Any]] = master["companies"]
        self._by_id = {item["id"]: item for item in self._companies}
        self._sources = {
            source["id"]: source.get("uri") or source.get("url")
            for source in manifest["sources"]
        }
        if len(self._by_id) != len(self._companies):
            raise ValueError("Duplicate company_id in company master")
        for company in self._companies:
            index = company.get("evidence_index_path")
            if index and not (self.root / index).is_file():
                raise FileNotFoundError(f"Company evidence index missing: {index}")

    @property
    def as_of_date(self) -> str:
        return self._as_of_date

    def list_companies(self) -> list[dict[str, Any]]:
        return list(self._companies)

    def get_company(self, company_id: str) -> dict[str, Any] | None:
        return self._by_id.get(company_id)

    def source_url(self, source_id: str) -> str | None:
        return self._sources.get(source_id)
