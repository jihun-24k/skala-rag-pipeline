#!/usr/bin/env python3
"""Run real A–F analysis and export JSON/Markdown; accepts `analyze` CLI flags."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from skala_rag.cli import main

if __name__ == '__main__':
    sys.argv.insert(1, 'analyze')
    raise SystemExit(main())
