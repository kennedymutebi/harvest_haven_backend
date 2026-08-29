"""
savings/reporting.py

Single source of truth for computing a member's numbers within one cycle.
Every export (Excel, PDF) and every summary view (member list, member
detail, collector analysis) should call these functions instead of
re-writing the aggregation logic — that's how we avoid the kind of
inconsistency that caused the negative-balance bug in the first place.
"""

from decimal import Decimal
from django.db.models import Sum
from .models import SavingsCycle, SavingsEntry, Withdrawal


def get_member_cycle_summary(member, cycle):
    """
    Everything needed for one row of a report: one member, one cycle.

    - opening_balance: ALWAYS zero. Cycles are fully independent by design;
      nothing carries over automatically.
    - carry_forward: the previous cycle's closing balance for this member,
      shown purely for reference. It never feeds into this cycle's math.
    - savings / withdrawals: totals strictly within THIS cycle.
    - closing_balance: savings - withdrawals, for this cycle only.
    - returned_amount: equals closing_balance once the cycle is closed
      (i.e. the amount actually paid out to the member at month-end).
      Zero while the cycle is still active/upcoming, since nothing has
      been paid out yet.
    """
    savings = SavingsEntry.objects.filter(
        member=member, cycle=cycle
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    withdrawals = Withdrawal.objects.filter(
        member=member, cycle=cycle
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    closing_balance = savings - withdrawals
    returned_amount = closing_balance if cycle.status == 'closed' else Decimal('0.00')
    carry_forward = _member_closing_balance_for_previous_cycle(member, cycle)

    return {
        'member': member,
        'cycle': cycle,
        'opening_balance': Decimal('0.00'),
        'carry_forward': carry_forward,
        'savings': savings,
        'withdrawals': withdrawals,
        'returned_amount': returned_amount,
        'closing_balance': closing_balance,
    }


def _member_closing_balance_for_previous_cycle(member, cycle):
    previous_cycle = cycle.previous_cycle()
    if not previous_cycle:
        return Decimal('0.00')

    prev_savings = SavingsEntry.objects.filter(
        member=member, cycle=previous_cycle
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    prev_withdrawals = Withdrawal.objects.filter(
        member=member, cycle=previous_cycle
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    return prev_savings - prev_withdrawals


def get_member_lifetime_history(member):
    """
    All cycles this member has any activity in, each with its own
    independent summary row (for 'one member's complete history' exports
    and the member detail page). Cycles are listed newest first.
    """
    cycle_ids = set(
        SavingsEntry.objects.filter(member=member).values_list('cycle_id', flat=True)
    ) | set(
        Withdrawal.objects.filter(member=member).exclude(cycle__isnull=True)
        .values_list('cycle_id', flat=True)
    )
    cycles = SavingsCycle.objects.filter(id__in=cycle_ids).order_by('-start_date')
    return [get_member_cycle_summary(member, cycle) for cycle in cycles]


def get_cycle_summary_for_all_members(cycle, members_queryset):
    """One row per member for a given cycle — the backbone of the
    'selected cycle/month' export and monthly reports."""
    return [get_member_cycle_summary(member, cycle) for member in members_queryset]


def get_collector_summary(collector, members_queryset, cycle=None):
    """
    Aggregate numbers for one collector, optionally scoped to one cycle.
    If cycle is None, sums each member's CURRENT (active-cycle-equivalent)
    figures across whichever cycle each row belongs to isn't meaningful —
    so all-time collector stats intentionally sum SavingsEntry/Withdrawal
    directly rather than cycle-by-cycle.
    """
    members = list(members_queryset)
    member_count = len(members)

    if cycle is not None:
        rows = [get_member_cycle_summary(m, cycle) for m in members]
        total_savings = sum((r['savings'] for r in rows), Decimal('0.00'))
        total_withdrawals = sum((r['withdrawals'] for r in rows), Decimal('0.00'))
        total_balance = sum((r['closing_balance'] for r in rows), Decimal('0.00'))
        total_returned = sum((r['returned_amount'] for r in rows), Decimal('0.00'))
        total_carry_forward = sum((r['carry_forward'] for r in rows), Decimal('0.00'))
    else:
        total_savings = SavingsEntry.objects.filter(
            member__in=members
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        total_withdrawals = Withdrawal.objects.filter(
            member__in=members
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        total_balance = total_savings - total_withdrawals
        total_returned = Decimal('0.00')  # not meaningful without a cycle
        total_carry_forward = Decimal('0.00')

    return {
        'collector': collector,
        'cycle': cycle,
        'member_count': member_count,
        'total_savings': total_savings,
        'total_withdrawals': total_withdrawals,
        'total_balance': total_balance,
        'amount_to_be_returned': total_returned,
        'amount_carried_forward': total_carry_forward,
    }