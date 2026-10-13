"""Paginated Korean PDF reports without a browser dependency."""
from __future__ import annotations

import os
import re
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
from reportlab.platypus import KeepTogether, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

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
               reference_heading: str = '참고문헌', financial_charts=(), investment_report=None) -> Path:
    font = register_font(font_path)
    body = ParagraphStyle('body', fontName=font, fontSize=9.5, leading=15.5,
                          wordWrap='CJK', spaceAfter=8, textColor=colors.HexColor('#243746'), alignment=TA_LEFT)
    heading = ParagraphStyle('heading', parent=body, fontSize=12, leading=18,
                             spaceBefore=17, spaceAfter=9, keepWithNext=True,
                             textColor=colors.HexColor('#15384f'))
    cell = ParagraphStyle('cell', parent=body, fontSize=8.5, leading=13, spaceAfter=0)
    code = ParagraphStyle('code', parent=body, fontSize=8, leading=11, spaceAfter=1)
    parser = MarkdownIt('commonmark').enable('table')
    story = [Paragraph(escape(title), ParagraphStyle('title', parent=heading,
                       fontSize=25, leading=34, spaceAfter=20))]

    if investment_report is not None:
        from skala_rag.agents.report import investment_snapshot
        assessment = investment_report.business_assessment
        signal = assessment.signal if assessment else 'undetermined'
        ink, fill = {'positive': ('#176445', '#eaf6ee'),
                     'undetermined': ('#795600', '#fff5d5'),
                     'concern': ('#a52b32', '#fdecee')}[signal]
        banner = ParagraphStyle('investment-banner', parent=body, fontSize=12, leading=19,
            textColor=colors.HexColor(ink), backColor=colors.HexColor(fill), borderPadding=11,
            spaceBefore=5, spaceAfter=20)
        story.append(Paragraph(escape(investment_snapshot(investment_report)).replace('\n\n', '<br/>'), banner))

    summary_style = ParagraphStyle('summary', parent=body, backColor=colors.HexColor('#f0f5f8'),
        borderPadding=10, spaceBefore=8, spaceAfter=14)
    reference_style = ParagraphStyle('reference', parent=body, fontSize=8, leading=12, spaceAfter=10)
    section_body = body

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
                href = child.attrGet('href') or ''
                links.append(href)
                rendered.append('<link href="' + escape(href, {'"': '&quot;'}) + '" color="#24758c">')
            elif child.type == 'link_close':
                if links:
                    links.pop()
                    rendered.append('</link>')
            elif child.type in ('text', 'code_inline', 'html_inline', 'image'):
                rendered.append(escape(child.content))
        return ''.join(rendered)

    def add_markdown(text):
        tokens = parser.parse(text)
        in_table = False
        rows = []
        style = section_body
        list_item = False
        for token in tokens:
            if token.type == 'table_open':
                in_table, rows = True, []
            elif token.type == 'tr_open':
                rows.append([])
            elif token.type == 'table_close':
                if rows:
                    width = A4[0] - 36 * mm
                    headers = [c.getPlainText() for c in rows[0]]
                    if len(headers) == 4 and '가중치' in headers:
                        ratios = [.21, .08, .20, .51]
                    elif len(headers) == 2:
                        ratios = [.27, .73]
                    else:
                        ratios = [1 / len(headers)] * len(headers)
                    table = LongTable(rows, colWidths=[width * r for r in ratios],
                                      repeatRows=1, splitInRow=1, hAlign='LEFT')
                    table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8eff4')),
                        ('LINEBELOW', (0, 0), (-1, 0), .7, colors.HexColor('#7693a5')),
                        ('LINEBELOW', (0, 1), (-1, -1), .25, colors.HexColor('#dce5eb')),
                        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7f9fb')]),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 7),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
                        ('TOPPADDING', (0, 0), (-1, -1), 7),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
                    ]))
                    if '가중치' in headers:
                        for row_index, row in enumerate(rows[1:], 1):
                            label = row[2].getPlainText()
                            color = '#eaf6ee' if '초록' in label else '#fdecee' if '빨강' in label else '#fff5d5'
                            table.setStyle(TableStyle([('BACKGROUND', (2, row_index), (2, row_index), colors.HexColor(color))]))
                    story.extend([KeepTogether([table]) if '가중치' in headers else table, Spacer(1, 8)])
                in_table = False
            elif token.type == 'heading_open':
                style = heading
            elif token.type == 'heading_close':
                style = section_body
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
        story.append(Paragraph(escape(name), heading))
        section_body = summary_style if name == '1. SUMMARY' else body
        add_markdown(content)
        if name == '9. FINANCIALS':
            for chart in financial_charts:
                story.extend([financial_chart_drawing(chart, font), Spacer(1, 10)])
    bibliography = [Paragraph(reference_heading, heading)]
    for index, reference in enumerate(report.references, 1):
        display = escape(f'[{index}] {reference}').replace('\n', '<br/>')
        display = re.sub(r'https?://[^\s<>]+',
            lambda m: '<link href="' + m.group(0).replace('"', '&quot;') + '" color="#24758c">원문 보기</link>', display)
        bibliography.append(Paragraph(display, reference_style))
    if not report.references:
        bibliography.append(Paragraph('확인된 참고문헌 없음', body))
    story.append(KeepTogether(bibliography))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#dce5eb'))
        canvas.line(18 * mm, 17 * mm, A4[0] - 18 * mm, 17 * mm)
        canvas.setFont(font, 7.5)
        canvas.setFillColor(colors.HexColor('#667788'))
        canvas.drawString(18 * mm, 12 * mm, title)
        canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f'{doc.page:02d}')
        canvas.restoreState()

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
        topMargin=18*mm, bottomMargin=20*mm, title=title, author='SKALA RAG')
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output


def render_evaluation_pdf(report, output: Path) -> Path:
    from skala_rag.agents.report import evaluation_report_sections
    # Presentation only: stored evidence IDs/claims remain unchanged for audit.
    sources = {}
    numbers = {}
    for eid, url in report.references.items():
        if url not in sources:
            sources[url] = (len(sources) + 1, eid)
        numbers[eid] = sources[url][0]
    def citations(text):
        for raw, label in {'robot_oem': '로봇 완제품 개발·제조',
                'source_supported_proposal': '출처 기반 잠정 분류',
                '확인 불가: tam': '확인 불가: 전체 시장(TAM)',
                '확인 불가: sam': '확인 불가: 유효 시장(SAM)',
                '확인 불가: som': '확인 불가: 확보 가능 시장(SOM)',
                '확인 불가: competition': '확인 불가: 경쟁 환경',
                '확인 불가: traction': '확인 불가: 사업 실적',
                '확인 불가: limitation': '확인 불가: 분석 한계',
                '확인 불가: domain': '확인 불가: 적용 분야',
                'not_confirmed_in_retrieved_evidence': '이번에 확보한 자료에서 확인되지 않음'}.items():
            text = text.replace(raw, label)
        def replace(match):
            ids = [value.strip() for value in match.group(1).split(',')]
            if ids and all(eid in numbers for eid in ids):
                return '[' + ', '.join(str(n) for n in dict.fromkeys(numbers[eid] for eid in ids)) + ']'
            return match.group(0)
        text = re.sub(r'\[([^\[\]\n]+)\]', replace, text)
        # MissingFact search records may contain bare IDs that are not cited claims.
        # Keep audit identifiers in JSON; never invent a bibliography entry for them.
        def checked_sources(match):
            return re.sub(r'\b(?:tech|market|financial):[A-Za-z0-9_-]+',
                lambda item: f'출처 {numbers[item.group(0)]}' if item.group(0) in numbers
                    else '조사 자료(상세 출처는 실행 기록 참조)', match.group(0))
        text = re.sub(r'확인한 자료:[^\n]*', checked_sources, text)
        # Preserve source access without printing tracking strings or long URLs.
        text = re.sub(r'https?://[^\s;|)]+',
            lambda m: '[출처 ' + str(sources[m.group(0)][0]) + '](' + m.group(0) + ')'
                if m.group(0) in sources else '[자료 보기](' + m.group(0) + ')', text)
        return text
    references = []
    for url, (_, eid) in sources.items():
        details = report.reference_details.get(eid, '')
        # Internal filesystem locations stay in JSON/Markdown, not the reader's bibliography.
        details = re.sub(r'원문 위치:.*$', '', details).replace('저자/발행기관 미확인. ', '')
        for raw, label in {'first_party': '회사 발표', 'patent': '특허', 'paper': '논문', 'academic': '학술 자료'}.items():
            if details.startswith(raw):
                details = label + details[len(raw):]
                break
        references.append(details.strip() + '\n' + url)
    carrier = InvestmentReport(summary=report.summary, technology='', market_competition='',
        financials='', risks='', decision='', references=references)
    return render_pdf(carrier, output, title=report.title,
        sections=[(name, citations(text)) for name, text in evaluation_report_sections(report)],
        reference_heading='14. REFERENCE', financial_charts=report.financial_charts, investment_report=report)


def evaluation_summary_fits(summary: str) -> bool:
    """실제 PDF와 같은 글꼴·폭·행간으로 반 페이지 상한을 측정한다."""
    style = ParagraphStyle('summary-check', fontName=register_font(), fontSize=9.5,
                           leading=15.5, wordWrap='CJK', spaceAfter=6)
    height = sum(Paragraph(escape(p).replace('\n', '<br/>'), style).wrap(A4[0] - 36 * mm, A4[1])[1] + 8
                 for p in summary.split('\n\n') if p.strip())
    return height <= (A4[1] - 38 * mm) / 2 - 46


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
