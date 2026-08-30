"""
savings/pdf_exports.py

PDF versions of the same reports as exports.py, built on the exact same
reporting.py functions — so a PDF and an Excel export of the same
cycle/member/collector always agree, by construction.
"""

from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from .reporting import (
    get_cycle_summary_for_all_members,
    get_member_lifetime_history,
    get_collector_summary,
)

BRAND_GREEN = colors.HexColor('#1DB954')
HEADER_STYLE = TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), BRAND_GREEN),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ('FONTSIZE', (0, 0), (-1, -1), 9),
    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5FBF7')]),
])

_styles = getSampleStyleSheet()
TITLE_STYLE = ParagraphStyle(
    'ReportTitle', parent=_styles['Heading1'], textColor=BRAND_GREEN, spaceAfter=4
)
SUBTITLE_STYLE = ParagraphStyle(
    'ReportSubtitle', parent=_styles['Normal'], textColor=colors.grey, spaceAfter=12
)


def _money(value):
    return f"{Decimal(value):,.2f}"


def _base_doc(buf):
    return SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
    )


def _to_bytes(story):
    buf = BytesIO()
    doc = _base_doc(buf)
    doc.build(story)
    buf.seek(0)
    return buf


def build_cycle_pdf(cycle, members_queryset):
    """One table, one row per member, for a single cycle — same data as
    the 'all members' / 'selected cycle' Excel export."""
    story = [
        Paragraph(f"{cycle.name} —  Twezimbe Development Group Savings Report", TITLE_STYLE),
        Paragraph(
            f"{cycle.start_date} to {cycle.end_date or 'ongoing'} &middot; "
            f"Status: {cycle.get_status_display()}",
            SUBTITLE_STYLE
        ),
    ]

    summaries = get_cycle_summary_for_all_members(cycle, members_queryset)

    data = [['Membership ID', 'Member Name', 'Carry Fwd', 'Savings', 'Withdrawals', 'Closing Bal', 'Returned']]
    for s in summaries:
        member = s['member']
        name = member.user.get_full_name() if hasattr(member, 'user') else str(member)
        data.append([
            member.membership_id, name,
            _money(s['carry_forward']), _money(s['savings']),
            _money(s['withdrawals']), _money(s['closing_balance']),
            _money(s['returned_amount']),
        ])

    total_savings = sum((s['savings'] for s in summaries), Decimal('0.00'))
    total_withdrawals = sum((s['withdrawals'] for s in summaries), Decimal('0.00'))
    total_closing = sum((s['closing_balance'] for s in summaries), Decimal('0.00'))
    total_returned = sum((s['returned_amount'] for s in summaries), Decimal('0.00'))
    data.append([
        '', 'TOTAL', '', _money(total_savings), _money(total_withdrawals),
        _money(total_closing), _money(total_returned),
    ])

    table = Table(data, repeatRows=1, hAlign='LEFT')
    style = TableStyle(HEADER_STYLE.getCommands())
    style.add('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold')
    style.add('LINEABOVE', (0, -1), (-1, -1), 1, colors.black)
    table.setStyle(style)
    story.append(table)

    return _to_bytes(story)


def build_member_statement_pdf(member):
    """One member's full history, one row per cycle they've ever touched —
    a printable statement, same data as the member-history Excel export."""
    name = member.user.get_full_name() if hasattr(member, 'user') else str(member)

    story = [
        Paragraph(" Twezimbe Development Group member Savings Statement", TITLE_STYLE),
        Paragraph(f"{name} &middot; Membership ID: {member.membership_id}", SUBTITLE_STYLE),
    ]

    history = get_member_lifetime_history(member)

    data = [['Cycle', 'Carry Fwd', 'Savings', 'Withdrawals', 'Closing Bal', 'Returned']]
    for s in history:
        data.append([
            s['cycle'].name,
            _money(s['carry_forward']), _money(s['savings']),
            _money(s['withdrawals']), _money(s['closing_balance']),
            _money(s['returned_amount']),
        ])

    if not history:
        story.append(Paragraph("No savings activity on record for this member.", _styles['Normal']))
    else:
        table = Table(data, repeatRows=1, hAlign='LEFT')
        table.setStyle(HEADER_STYLE)
        story.append(table)

    return _to_bytes(story)


def build_collector_pdf(collector, members_queryset, cycle=None):
    """One-page summary card for a single collector — same numbers as
    the collector Excel export."""
    story = [
        Paragraph(f" Twezimbe Development Group Collector Summary — {collector.name}", TITLE_STYLE),
    ]
    if cycle:
        story.append(Paragraph(f"Cycle: {cycle.name}", SUBTITLE_STYLE))
    else:
        story.append(Paragraph("All-time", SUBTITLE_STYLE))
    story.append(Spacer(1, 6))

    summary = get_collector_summary(collector, members_queryset, cycle=cycle)

    data = [
        ['Member Count', str(summary['member_count'])],
        ['Total Savings', _money(summary['total_savings'])],
        ['Total Withdrawals', _money(summary['total_withdrawals'])],
        ['Total Balance', _money(summary['total_balance'])],
        ['Amount to be Returned', _money(summary['amount_to_be_returned'])],
        ['Amount Carried Forward', _money(summary['amount_carried_forward'])],
    ]
    table = Table(data, colWidths=[70 * mm, 60 * mm], hAlign='LEFT')
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F5FBF7')),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(table)

    return _to_bytes(story)