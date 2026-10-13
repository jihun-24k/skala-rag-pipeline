"""Paginated Korean PDF reports without a browser dependency."""
from __future__ import annotations

import os
from pathlib import Path
from xml.sax.saxutils import escape

from markdown_it import MarkdownIt
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from skala_rag.models import InvestmentReport


def register_font(font_path: Path | None = None) -> str:
    candidates = [font_path, os.getenv('SKALA_PDF_FONT'),
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
        'C:/Windows/Fonts/malgun.ttf']
    selected = next((Path(p) for p in candidates if p and Path(p).is_file()), None)
    if selected is None:
        raise ValueError('한글 TTF 글꼴이 필요합니다. SKALA_PDF_FONT에 NanumGothic.ttf 등의 경로를 설정하세요.')
    import hashlib
    name = 'Korean-' + hashlib.sha256(str(selected.resolve()).encode()).hexdigest()[:12]
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(selected)))
        pdfmetrics.registerFontFamily(name, normal=name, bold=name, italic=name, boldItalic=name)
    return name


def render_pdf(report: InvestmentReport, output: Path, *, title: str = '투자 분석 보고서',
               font_path: Path | None = None, sections: list[tuple[str, str]] | None = None,
               reference_heading: str = '참고문헌', financial_charts=()) -> Path:
    font = register_font(font_path)
    body = ParagraphStyle('body', fontName=font, fontSize=9, leading=14,
                          wordWrap='CJK', spaceAfter=6, alignment=TA_LEFT)
    heading = ParagraphStyle('heading', parent=body, fontSize=13, leading=19,
                             spaceBefore=12, spaceAfter=7, keepWithNext=True,
                             textColor=colors.HexColor('#15384f'))
    cell = ParagraphStyle('cell', parent=body, fontSize=8, leading=12, spaceAfter=0)
    code = ParagraphStyle('code', parent=body, fontSize=8, leading=11, spaceAfter=1)
    parser = MarkdownIt('commonmark').enable('table')
    story = [Paragraph(escape(title), ParagraphStyle('title', parent=heading,
                       fontSize=21, leading=28, spaceAfter=16))]

    def inline(token):
        rendered = []
        links = []
        for child in token.children or []:
            if child.type in ('softbreak', 'hardbreak'):
                rendered.append('<br/>')
            elif child.type == 'strong_open':
                rendered.append('<b>')
            elif child.type == 'strong_close':
                rendered.append('</b>')
            elif child.type == 'em_open':
                rendered.append('<i>')
            elif child.type == 'em_close':
                rendered.append('</i>')
            elif child.type == 'link_open':
                links.append(child.attrGet('href') or '')
            elif child.type == 'link_close':
                if links:
                    rendered.append(' (' + escape(links.pop()) + ')')
            elif child.type in ('text', 'code_inline', 'html_inline', 'image'):
                rendered.append(escape(child.content))
        return ''.join(rendered)

    def add_markdown(text):
        tokens = parser.parse(text)
        in_table = False
        rows = []
        style = body
        list_item = False
        for token in tokens:
            if token.type == 'table_open':
                in_table, rows = True, []
            elif token.type == 'tr_open':
                rows.append([])
            elif token.type == 'table_close':
                if rows:
                    width = A4[0] - 36 * mm
                    table = LongTable(rows, colWidths=[width / len(rows[0])] * len(rows[0]),
                                      repeatRows=1, splitInRow=1, hAlign='LEFT')
                    table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8eff4')),
                        ('GRID', (0, 0), (-1, -1), .3, colors.HexColor('#c9d3da')),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 5),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                        ('TOPPADDING', (0, 0), (-1, -1), 5),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                    ]))
                    story.extend([table, Spacer(1, 8)])
                in_table = False
            elif token.type == 'heading_open':
                style = heading
            elif token.type == 'heading_close':
                style = body
            elif token.type == 'list_item_open':
                list_item = True
            elif token.type == 'inline':
                prefix = '- ' if list_item else ''
                list_item = False
                paragraph = Paragraph(prefix + (inline(token) or ' '), cell if in_table else style)
                if in_table:
                    rows[-1].append(paragraph)
                else:
                    story.append(paragraph)
            elif token.type in ('fence', 'code_block'):
                for line in token.content.splitlines():
                    story.append(Paragraph(escape(line) or ' ', code))
                story.append(Spacer(1, 6))
            elif token.type == 'html_block':
                story.append(Paragraph(escape(token.content), body))

    sections = sections if sections is not None else [('요약', report.summary), ('기술 분석', report.technology),
                ('시장·경쟁 분석', report.market_competition), ('재무 분석', report.financials),
                ('위험 및 확인 사항', report.risks), ('투자 판단', report.decision)]
    for name, content in sections:
        story.append(Paragraph(name, heading))
        add_markdown(content)
        if name == '9. FINANCIALS':
            for chart in financial_charts:
                story.extend([financial_chart_drawing(chart, font), Spacer(1, 10)])
    story.append(Paragraph(reference_heading, heading))
    for index, reference in enumerate(report.references, 1):
        story.append(Paragraph(escape(f'{index}. {reference}'), body))
    if not report.references:
        story.append(Paragraph('확인된 참고문헌 없음', body))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor('#667788'))
        canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f'{doc.page}')
        canvas.restoreState()

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
        topMargin=18*mm, bottomMargin=20*mm, title=title, author='SKALA RAG')
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output


def render_evaluation_pdf(report, output: Path) -> Path:
    from skala_rag.agents.report import evaluation_report_sections, evaluation_reference_lines
    carrier = InvestmentReport(summary=report.summary, technology='', market_competition='',
        financials='', risks='', decision='', references=evaluation_reference_lines(report))
    return render_pdf(carrier, output, title=report.title,
        sections=evaluation_report_sections(report), reference_heading='14. REFERENCE',
        financial_charts=report.financial_charts)


def evaluation_summary_fits(summary: str) -> bool:
    """실제 PDF와 같은 글꼴·폭·행간으로 반 페이지 상한을 측정한다."""
    style = ParagraphStyle('summary-check', fontName=register_font(), fontSize=9,
                           leading=14, wordWrap='CJK', spaceAfter=6)
    height = sum(Paragraph(escape(p).replace('\n', '<br/>'), style).wrap(A4[0] - 36 * mm, A4[1])[1] + 6
                 for p in summary.split('\n\n') if p.strip())
    return height <= (A4[1] - 38 * mm) / 2 - 26


def financial_chart_drawing(chart, font):
    """Vector bars with zero baseline (including losses), exact figures in adjacent table."""
    from reportlab.graphics.shapes import Drawing, String, Line, Rect
    width, height = A4[0] - 36 * mm, 156
    drawing = Drawing(width, height)
    scope = '연결' if chart.statement_scope == 'consolidated' else '별도'
    drawing.add(String(0, 140, f'{chart.title} ({scope}, {chart.unit})', fontName=font, fontSize=10))
    values = [p.value for p in chart.points]
    low, high = min(0, min(values)), max(0, max(values))
    span = high - low or 1
    bottom, plot_height = 32, 84
    def y(value):
        return bottom + (value - low) / span * plot_height
    drawing.add(Line(0, y(0), width, y(0), strokeColor=colors.HexColor('#9aabba')))
    step = width / len(values)
    for index, point in enumerate(chart.points):
        x, bar_width = index * step + step * .3, step * .4
        drawing.add(Rect(x, min(y(0), y(point.value)), bar_width, abs(y(point.value)-y(0)),
            fillColor=colors.HexColor('#24758c' if point.value >= 0 else '#b75050'), strokeColor=None))
        drawing.add(String(x + bar_width / 2, y(point.value) + (4 if point.value >= 0 else -10),
            f'{point.value:,.0f}', fontName=font, fontSize=8, textAnchor='middle'))
        drawing.add(String(x + bar_width / 2, 6, point.period, fontName=font, fontSize=8, textAnchor='middle'))
    return drawing
