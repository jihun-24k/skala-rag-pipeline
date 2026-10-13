#!/usr/bin/env python3
"""Repository entrypoint; options default to the Supervisor workflow."""
from __future__ import annotations

import sys
import os
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    environment = root / '.venv'
    interpreter = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if interpreter.is_file() and Path(sys.prefix).resolve() != environment.resolve():
        # Use the project's synchronized dependencies even from a system Python.
        os.execv(str(interpreter), [str(interpreter), str(root / 'app.py'), *sys.argv[1:]])
    # Support the src layout when running directly from an uninstalled checkout.
    sys.path.insert(0, str(root / 'src'))
    try:
        from skala_rag.cli import main as cli_main
    except ImportError as exc:
        print(f'Error: {exc}\n의존성을 설치하세요: uv sync --extra llm --group dev', file=sys.stderr)
        return 1

    arguments = sys.argv[1:]
    if not arguments:
        arguments = ['orchestrate', '--help']
    elif arguments[0].startswith('-'):
        arguments = ['orchestrate', *arguments]
    return cli_main(arguments, prog='python app.py')


if __name__ == '__main__':
    raise SystemExit(main())
