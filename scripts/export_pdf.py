"""보고서 Markdown → A4 PDF 변환 + 페이지 수 확인.

    uv pip install markdown pypdf playwright && playwright install chromium   # 처음 한 번
    PYTHONPATH=src:. python scripts/export_pdf.py storage/reports/robros_2026-09-30.md

두 가지 레이아웃으로 만들어 장수를 비교한다.
    continuous : 내용을 이어서 배치 → 보고서 전체가 5페이지 안에 들어가는지
    per-page   : 설계서의 PAGE 1~5(--- 구분)마다 새 페이지 → 각 설계 페이지가 한 장에 들어가는지
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import markdown
from pypdf import PdfReader

PAGE_LIMIT = 5

CSS = """
@page { size: A4; margin: 16mm 15mm; }
body { font-family: 'Apple SD Gothic Neo', 'Noto Sans CJK KR', 'Malgun Gothic', sans-serif;
       font-size: 9.5pt; line-height: 1.5; color: #111; }
h1 { font-size: 16pt; margin: 0 0 4pt; }
h2 { font-size: 12pt; margin: 10pt 0 4pt; border-bottom: 1px solid #999; padding-bottom: 2pt; }
h3 { font-size: 10.5pt; margin: 8pt 0 3pt; }
p, li { margin: 3pt 0; }
blockquote { margin: 0 0 6pt; padding: 4pt 8pt; background: #f3f3f3; border-left: 3px solid #666; }
table { border-collapse: collapse; width: 100%; font-size: 8.5pt; margin: 4pt 0 6pt; page-break-inside: avoid; }
th, td { border: 1px solid #bbb; padding: 2.5pt 4pt; vertical-align: top; overflow-wrap: anywhere; }
p, li, td { word-break: break-all; }
th { background: #eee; }
hr { border: 0; margin: 6pt 0; }
"""
BREAK_CSS = "hr { page-break-after: always; break-after: page; visibility: hidden; margin: 0; }"


def to_html(md_text: str, per_page: bool) -> str:
    body = markdown.markdown(md_text, extensions=["tables"])
    css = CSS + (BREAK_CSS if per_page else "")
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"


def html_to_pdf(html: str, out: Path) -> None:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
            browser.close()
        return
    except Exception as e:  # playwright 미설치 또는 브라우저 없음 → wkhtmltopdf
        if not shutil.which("wkhtmltopdf"):
            raise SystemExit("PDF 변환기가 없습니다. `uv pip install playwright && playwright install chromium`을 "
                             f"실행하세요. ({type(e).__name__})")
    # wkhtmltopdf(QtWebKit)는 pt를 96dpi 기준으로 그려 글자가 약 79% 크기로 작아진다 → 배율 보정
    html = html.replace("</style>", "html { zoom: 1.267; }</style>", 1)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
    subprocess.run(["wkhtmltopdf", "--quiet", "--disable-smart-shrinking", "--page-size", "A4", "--encoding", "utf-8",
                    "-T", "16mm", "-B", "16mm", "-L", "15mm", "-R", "15mm", f.name, str(out)], check=True)


def export(md_path: Path) -> dict[str, tuple[Path, int]]:
    md_text = md_path.read_text(encoding="utf-8")
    result = {}
    for mode, per_page in (("continuous", False), ("per-page", True)):
        out = md_path.with_name(f"{md_path.stem}{'' if mode == 'continuous' else '_per-page'}.pdf")
        html_to_pdf(to_html(md_text, per_page), out)
        result[mode] = (out, len(PdfReader(str(out)).pages))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown_file", type=Path)
    args = parser.parse_args()
    res = export(args.markdown_file)
    cont, per = res["continuous"][1], res["per-page"][1]
    print(f"이어서 배치: {cont}쪽 → {res['continuous'][0]}")
    print(f"설계 페이지별 배치: {per}쪽 → {res['per-page'][0]}")
    print(f"판정: 5페이지 제한 {'충족' if cont <= PAGE_LIMIT else '초과'}"
          + ("" if per <= PAGE_LIMIT else f" (설계 PAGE 중 {per - PAGE_LIMIT}쪽이 한 장을 넘침)"))


if __name__ == "__main__":
    main()
