#!/usr/bin/env python3
"""Run local repository, test-suite, and FAISS artifact validation.

Usage:
    python scripts/verify_repository.py
    python scripts/verify_repository.py --skip-tests
    python scripts/verify_repository.py --index storage/indexes/qwen3-0.6b-v1

The script intentionally uses only the Python standard library for orchestration,
so it can still report a broken environment or lock file.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sqlite3
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "storage/indexes/qwen3-0.6b-v1"


@dataclass(slots=True)
class Result:
    name: str
    status: str
    detail: str


RESULTS: list[Result] = []


def record(name: str, status: str, detail: str) -> None:
    RESULTS.append(Result(name, status, detail))
    symbol = {"PASS": "✓", "WARN": "!", "FAIL": "✗"}[status]
    print(f"[{symbol}] {name}: {detail}")


def run_command(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    source_path = str(ROOT / "src")
    environment.setdefault("UV_CACHE_DIR", str(ROOT / ".uv-cache"))
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_path, environment.get("PYTHONPATH", "")) if part
    )
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def concise_output(output: str, *, lines: int = 18) -> str:
    values = [line.rstrip() for line in output.splitlines() if line.strip()]
    return "\n".join(values[-lines:]) or "출력 없음"


def check_python() -> None:
    version = sys.version_info
    if version < (3, 11):
        record("Python", "FAIL", f"3.11 이상 필요, 현재 {version.major}.{version.minor}")
        return
    record("Python", "PASS", f"{version.major}.{version.minor}.{version.micro}")


def check_project_metadata() -> None:
    path = ROOT / "pyproject.toml"
    try:
        project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
        required = {"faiss-cpu", "sentence-transformers", "pypdf"}
        dependencies = {
            item.split("<", 1)[0].split(">", 1)[0].split("=", 1)[0].strip()
            for item in project.get("dependencies", [])
        }
        missing = sorted(required - dependencies)
        if missing:
            record("pyproject.toml", "FAIL", f"필수 의존성 누락: {', '.join(missing)}")
            return
        record("pyproject.toml", "PASS", f"{project['name']} {project['version']}")
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        record("pyproject.toml", "FAIL", str(exc))


def check_uv_lock() -> None:
    try:
        process = run_command(["uv", "lock", "--check"], timeout=120)
    except FileNotFoundError:
        record("uv.lock", "WARN", "uv 명령을 찾을 수 없어 건너뜀")
        return
    if process.returncode:
        record("uv.lock", "FAIL", concise_output(process.stdout, lines=8))
        return
    record("uv.lock", "PASS", "pyproject.toml과 잠금파일이 일치함")


def check_conflict_markers() -> None:
    process = run_command(
        ["git", "grep", "-n", "-E", r"^(<<<<<<< |>>>>>>> )", "--", "."],
        timeout=60,
    )
    if process.returncode == 1:
        record("병합 마커", "PASS", "추적 파일에 충돌 마커 없음")
    elif process.returncode == 0:
        record("병합 마커", "FAIL", concise_output(process.stdout))
    else:
        record("병합 마커", "FAIL", concise_output(process.stdout))


def check_compile() -> None:
    process = run_command(
        [sys.executable, "-m", "compileall", "-q", "src", "scripts"], timeout=120
    )
    if process.returncode:
        record("소스 컴파일", "FAIL", concise_output(process.stdout))
        return
    record("소스 컴파일", "PASS", "src/와 scripts/ 구문 검사 통과")


def check_imports() -> None:
    modules = (
        "skala_rag",
        "skala_rag.graph",
        "skala_rag.ingestion",
        "skala_rag.retrieval",
    )
    failures: list[str] = []
    sys.path.insert(0, str(ROOT / "src"))
    for module in modules:
        try:
            importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 - validation must report every import error
            failures.append(f"{module}: {type(exc).__name__}: {exc}")
    if failures:
        record("핵심 import", "FAIL", "\n".join(failures))
        return
    record("핵심 import", "PASS", f"{len(modules)}개 모듈")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_faiss_index(index_dir: Path) -> None:
    if not index_dir.exists():
        record("FAISS 인덱스", "WARN", f"없음: {index_dir.relative_to(ROOT)}")
        return

    try:
        manifest_path = index_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_files: dict[str, str] = manifest["files"]
        for name, expected_hash in expected_files.items():
            artifact = index_dir / name
            if not artifact.is_file():
                raise ValueError(f"인덱스 파일 누락: {name}")
            if sha256_file(artifact) != expected_hash:
                raise ValueError(f"체크섬 불일치: {name}")

        metadata_path = index_dir / "metadata.sqlite3"
        with sqlite3.connect(metadata_path) as connection:
            sqlite_count = int(
                connection.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
            )

        import faiss

        if sys.platform == "darwin":
            faiss.omp_set_num_threads(1)
        faiss_count = int(faiss.read_index(str(index_dir / "evidence.faiss")).ntotal)
        manifest_count = int(manifest["chunk_count"])
        if not (manifest_count == sqlite_count == faiss_count):
            raise ValueError(
                "청크 수 불일치: "
                f"manifest={manifest_count}, sqlite={sqlite_count}, faiss={faiss_count}"
            )
        record(
            "FAISS 인덱스",
            "PASS",
            f"{faiss_count} vectors, {manifest['embedding_model']}, 체크섬 정상",
        )
    except (ImportError, OSError, KeyError, json.JSONDecodeError, sqlite3.Error, ValueError) as exc:
        record("FAISS 인덱스", "FAIL", str(exc))


def check_tests() -> None:
    try:
        process = run_command([sys.executable, "-m", "pytest", "-q"], timeout=600)
    except FileNotFoundError:
        record("pytest", "FAIL", "현재 Python에서 pytest를 실행할 수 없음")
        return
    except subprocess.TimeoutExpired:
        record("pytest", "FAIL", "10분 제한시간 초과")
        return
    if process.returncode:
        record("pytest", "FAIL", concise_output(process.stdout, lines=25))
        return
    record("pytest", "PASS", concise_output(process.stdout, lines=3))


def execute(name: str, check: Callable[[], None]) -> None:
    try:
        check()
    except Exception as exc:  # noqa: BLE001 - one failed check must not hide later checks
        record(name, "FAIL", f"{type(exc).__name__}: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX,
        help="검증할 FAISS 인덱스 디렉터리",
    )
    parser.add_argument("--skip-tests", action="store_true", help="pytest 실행 생략")
    parser.add_argument("--skip-uv", action="store_true", help="uv.lock 검사 생략")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    index_dir = args.index if args.index.is_absolute() else ROOT / args.index
    print(f"SKALA RAG 저장소 검증: {ROOT}")
    print("=" * 72)

    execute("Python", check_python)
    execute("pyproject.toml", check_project_metadata)
    if not args.skip_uv:
        execute("uv.lock", check_uv_lock)
    execute("병합 마커", check_conflict_markers)
    execute("소스 컴파일", check_compile)
    execute("핵심 import", check_imports)
    execute("FAISS 인덱스", lambda: check_faiss_index(index_dir.resolve()))
    if not args.skip_tests:
        execute("pytest", check_tests)

    failures = [result for result in RESULTS if result.status == "FAIL"]
    warnings = [result for result in RESULTS if result.status == "WARN"]
    print("=" * 72)
    print(
        f"결과: PASS {len(RESULTS) - len(failures) - len(warnings)} / "
        f"WARN {len(warnings)} / FAIL {len(failures)}"
    )
    if failures:
        print("실패 항목: " + ", ".join(result.name for result in failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
