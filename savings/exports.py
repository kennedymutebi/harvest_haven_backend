"""
savings/exports.py

Excel export builders. Every function here turns reporting.py's summary
dicts into an openpyxl workbook — no separate calculation logic, so the
numbers always match what reporting.py (and therefore the on-screen
views) say.
"""

from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from .reporting import (
    get_member_cycle_summary,
    get_cycle_summary_for_all_members,
    get_member_lifetime_history,
    get_collector_summary,
)

HEADER_FILL = PatternFill(start_color='1DB954', end_color='1DB954', fill_type='solid')
HEADER_FONT = Font(color='FFFFFF', bold=True)
MONEY_FORMAT = '#,##0.00'


def _write_header(ws, headers, row=1):
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col_idx, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal='center')
    return row + 1


def _autosize(ws, headers):
    for col_idx, header in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = max(len(str(header)) + 4, 14)


def _to_response_bytes(wb):
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


CYCLE_HEADERS = [
    'Membership ID', 'Member Name', 'Carry Forward', 'Savings',
    'Withdrawals', 'Closing Balance', 'Returned Amount',
]


def _write_cycle_row(ws, row, summary):
    member = summary['member']
    values = [
        member.membership_id,
        member.user.get_full_name() if hasattr(member, 'user') else str(member),
        summary['carry_forward'],
        summary['savings'],
        summary['withdrawals'],
        summary['closing_balance'],
        summary['returned_amount'],
    ]
    for col_idx, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col_idx, value=value)
        if isinstance(value, Decimal):
            cell.number_format = MONEY_FORMAT
    return row + 1


def build_cycle_export(cycle, members_queryset):
    """One sheet, one row per member, for a single cycle. This is the
    'selected cycle/month' export AND the 'all members' export — 'all
    members' is just this cycle set to the active cycle."""
    wb = Workbook()
    ws = wb.active
    ws.title = (cycle.name or 'Cycle')[:31]

    ws.cell(row=1, column=1, value=f"Cycle: {cycle.name}  ({cycle.start_date} - {cycle.end_date or 'ongoing'})")
    ws.cell(row=1, column=1).font = Font(bold=True, size=12)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(CYCLE_HEADERS))

    header_row = _write_header(ws, CYCLE_HEADERS, row=3)
    row = header_row
    summaries = get_cycle_summary_for_all_members(cycle, members_queryset)
    for summary in summaries:
        row = _write_cycle_row(ws, row, summary)

    # Totals row
    ws.cell(row=row, column=2, value='TOTAL').font = Font(bold=True)
    for col_idx, key in [(4, 'savings'), (5, 'withdrawals'), (6, 'closing_balance'), (7, 'returned_amount')]:
        total = sum((s[key] for s in summaries), Decimal('0.00'))
        cell = ws.cell(row=row, column=col_idx, value=total)
        cell.number_format = MONEY_FORMAT
        cell.font = Font(bold=True)

    _autosize(ws, CYCLE_HEADERS)
    return _to_response_bytes(wb)


def build_member_history_export(member):
    """One sheet, one row per cycle the member has ever touched —
    their complete history, newest cycle first."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'History'[:31]

    name = member.user.get_full_name() if hasattr(member, 'user') else str(member)
    ws.cell(row=1, column=1, value=f"Member: {name} ({member.membership_id})")
    ws.cell(row=1, column=1).font = Font(bold=True, size=12)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)

    headers = ['Cycle', 'Carry Forward', 'Savings', 'Withdrawals', 'Closing Balance', 'Returned Amount']
    header_row = _write_header(ws, headers, row=3)
    row = header_row

    for summary in get_member_lifetime_history(member):
        values = [
            summary['cycle'].name,
            summary['carry_forward'],
            summary['savings'],
            summary['withdrawals'],
            summary['closing_balance'],
            summary['returned_amount'],
        ]
        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col_idx, value=value)
            if isinstance(value, Decimal):
                cell.number_format = MONEY_FORMAT
        row += 1

    _autosize(ws, headers)
    return _to_response_bytes(wb)


COLLECTOR_HEADERS = [
    'Collector', 'Member Count', 'Total Savings', 'Total Withdrawals',
    'Total Balance', 'Amount to be Returned', 'Amount Carried Forward',
]


def build_collector_export(collector, members_queryset, cycle=None):
    """One sheet, one row: aggregate stats for one collector, optionally
    scoped to a cycle."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Collector Summary'[:31]

    header_row = _write_header(ws, COLLECTOR_HEADERS, row=1)
    summary = get_collector_summary(collector, members_queryset, cycle=cycle)

    values = [
        collector.get_full_name() if hasattr(collector, 'get_full_name') else str(collector),
        summary['member_count'],
        summary['total_savings'],
        summary['total_withdrawals'],
        summary['total_balance'],
        summary['amount_to_be_returned'],
        summary['amount_carried_forward'],
    ]
    for col_idx, value in enumerate(values, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=value)
        if isinstance(value, Decimal):
            cell.number_format = MONEY_FORMAT

    _autosize(ws, COLLECTOR_HEADERS)
    return _to_response_bytes(wb)


def build_all_collectors_export(collectors_with_members, cycle=None):
    """One sheet, one row per collector — for the 'all collectors'
    comparison export. collectors_with_members is an iterable of
    (collector, members_queryset) tuples."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'All Collectors'[:31]

    header_row = _write_header(ws, COLLECTOR_HEADERS, row=1)
    row = header_row

    for collector, members_queryset in collectors_with_members:
        summary = get_collector_summary(collector, members_queryset, cycle=cycle)
        values = [
            collector.get_full_name() if hasattr(collector, 'get_full_name') else str(collector),
            summary['member_count'],
            summary['total_savings'],
            summary['total_withdrawals'],
            summary['total_balance'],
            summary['amount_to_be_returned'],
            summary['amount_carried_forward'],
        ]
        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col_idx, value=value)
            if isinstance(value, Decimal):
                cell.number_format = MONEY_FORMAT
        row += 1

    _autosize(ws, COLLECTOR_HEADERS)
    return _to_response_bytes(wb)