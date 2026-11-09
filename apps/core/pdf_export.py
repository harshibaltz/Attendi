"""PDF table export helper.

PDF is a binary response, so it bypasses the DRF JSON envelope just like the
CSV helper. ReportLab keeps the dependency pure Python and works on Vercel.
"""
from datetime import date, datetime
from io import BytesIO
from xml.sax.saxutils import escape

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_PRIMARY = colors.HexColor("#3F35B5")
_BORDER = colors.HexColor("#D9D9E3")
_STRIPE = colors.HexColor("#F7F7FB")
_MUTED = colors.HexColor("#666677")


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _paragraph(text, style):
    return Paragraph(escape(_cell(text)), style)


def pdf_table_response(filename, title, subtitle, header, rows, column_weights=None):
    """Render a landscape A4 table and return it as a downloadable PDF."""
    buffer = BytesIO()
    page_width, _page_height = landscape(A4)
    margin = 12 * mm
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=title,
        author="FET Platform",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "FetPdfTitle", parent=styles["Title"], fontSize=14, leading=18,
        textColor=_PRIMARY, alignment=0, spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "FetPdfSubtitle", parent=styles["Normal"], fontSize=8.5, leading=11,
        textColor=_MUTED, spaceAfter=8,
    )
    cell_style = ParagraphStyle(
        "FetPdfCell", parent=styles["Normal"], fontSize=7.5, leading=9.5,
    )
    header_style = ParagraphStyle(
        "FetPdfHeader", parent=cell_style, fontName="Helvetica-Bold",
        textColor=colors.white,
    )

    story = [
        Paragraph(escape(title), title_style),
        Paragraph(escape(subtitle), subtitle_style),
        Spacer(1, 2),
    ]

    table_data = [
        [_paragraph(cell, header_style) for cell in header],
        *[[_paragraph(cell, cell_style) for cell in row] for row in rows],
    ]
    available = page_width - (2 * margin)
    weights = column_weights or [0.24, 0.10, 0.26, 0.14, 0.07, 0.08, 0.11]
    if len(header) != len(weights):
        weights = [1 / len(header)] * len(header)
    widths = [available * weight for weight in weights]

    table = Table(table_data, repeatRows=1, colWidths=widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _PRIMARY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, _BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _STRIPE]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)

    def _footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(_MUTED)
        canvas.drawRightString(
            page_width - margin, 7 * mm, f"Page {document.page}",
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
