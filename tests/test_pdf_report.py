from argparse import Namespace
from pathlib import Path

from pypdf import PdfReader
import pytest

from skala_rag.cli import _report_command
from skala_rag.models import InvestmentReport
from skala_rag.pdf_report import register_font, render_pdf


@pytest.fixture(autouse=True)
def korean_font():
    try:
        register_font()
    except ValueError:
        pytest.skip('Set SKALA_PDF_FONT to run Korean PDF rendering tests')


def report():
    return InvestmentReport(summary='한글 보고서 검증 <script> & 안전한 출력',
        technology='## 핵심 기술\n- 정밀 제어\n- **제품 검증**',
        market_competition='| 항목 | 내용 |\n| --- | --- |\n' +
            '\n'.join(f'| 시장 {i} | 성장 가능성과 자료의 한계 확인 |' for i in range(100)),
        financials='```json\n{"매출": null}\n```', risks='추가 확인 필요',
        decision='추가 실사', references=['https://example.org/' + 'reference-' * 80])


def test_pdf_has_extractable_korean_paginated_tables_and_embedded_font(tmp_path):
    output = render_pdf(report(), tmp_path / 'report.pdf')
    reader = PdfReader(output)
    assert len(reader.pages) >= 3
    text = '\n'.join(page.extract_text() for page in reader.pages)
    assert '한글 보고서 검증' in text
    assert '시장 99' in text
    assert '참고문헌' in text
    assert all(round(float(p.mediabox.width)) == 595 for p in reader.pages)
    fonts = reader.pages[0]['/Resources']['/Font'].get_object()
    assert any('/FontFile2' in f.get_object().get('/FontDescriptor', {}) for f in fonts.values())


def test_report_cli_writes_pdf_not_markdown_with_pdf_suffix(tmp_path):
    import json
    source = tmp_path / 'state.json'
    source.write_text(json.dumps({'report': report().model_dump()}), encoding='utf-8')
    target = tmp_path / 'out.pdf'
    assert _report_command(Namespace(input=source, output=target)) == 0
    assert target.read_bytes().startswith(b'%PDF-')
    with pytest.raises(ValueError, match='must use'):
        _report_command(Namespace(input=source, output=tmp_path / 'out.txt'))
