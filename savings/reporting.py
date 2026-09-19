"""
savings/reporting.py  (REWRITTEN)

The old version of this file computed `carry_forward` but explicitly never
added it into `closing_balance` - "opening_balance ALWAYS zero, cycles are
fully independent by design." That was the actual cause of the Section-1
bug ("savings looks like it resets"). This version fixes it by delegating
the B/F math to the tested domain layer (savings_domain/balance.py)
instead of re-deriving it ad hoc here.

Every export (Excel, PDF) and every summary view should still call these
functions - the public function names and return-dict shapes are kept
the same on purpose, so views.py / exports.py / pdf_exports.py need
NO changes to keep working. Only the numbers they receive are now correct.
"""

from decimal import Decimal

from django.db.models import Sum

from .models import SavingsCycle, SavingsEntry, Withdrawal
from .infrastructure import get_member_balance


def get_member_cycle_summary(member, cycle):
    """
    Everything needed for one row of a report: one member, one cycle.

    - opening_balance: the member's Brought Forward balance as of the
      START of this cycle - i.e. everything they had before this month,
      still available. (Previously hardcoded to zero.)
    - carry_forward: kept as an alias of opening_balance for backward
      compatibility with any existing caller/frontend field name.
    - savings / withdrawals: totals strictly within THIS cycle (unchanged
      meaning - still useful for "what happened this month" reporting).
    - closing_balance: NOW opening_balance + savings - withdrawals, i.e.
      the member's real Total Balance at this point in time. This is the
      field that actually fixes the "looks like it resets" bug.
    - returned_amount: equals closing_balance once the cycle is closed
      (unchanged meaning).
    """
    balance = get_member_balance(member.id, cycle)

    savings = SavingsEntry.objects.filter(
        member=member, cycle=cycle
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    withdrawals = Withdrawal.objects.filter(
        member=member, cycle=cycle
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    opening_balance = balance.brought_forward.amount
    closing_balance = balance.total.amount
    returned_amount = closing_balance if cycle.status == 'closed' else Decimal('0.00')

    return {
        'member': member,
        'cycle': cycle,
        'opening_balance': opening_balance,
        'carry_forward': opening_balance,  # kept for backward compatibility
        'savings': savings,
        'withdrawals': withdrawals,
        'returned_amount': returned_amount,
        'closing_balance': closing_balance,
    }


def get_member_lifetime_history(member):
    """All cycles this member has any activity in, each with its own
    summary row. Cycles are listed newest first. Unchanged from before."""
    cycle_ids = set(
        SavingsEntry.objects.filter(member=member).values_list('cycle_id', flat=True)
    ) | set(
        Withdrawal.objects.filter(member=member).exclude(cycle__isnull=True)
        .values_list('cycle_id', flat=True)
    )
    cycles = SavingsCycle.objects.filter(id__in=cycle_ids).order_by('-start_date')
    return [get_member_cycle_summary(member, cycle) for cycle in cycles]


def get_cycle_summary_for_all_members(cycle, members_queryset):
    """One row per member for a given cycle - unchanged shape, correct
    numbers now."""
    return [get_member_cycle_summary(member, cycle) for member in members_queryset]


def get_collector_summary(collector, members_queryset, cycle=None):
    """Aggregate numbers for one collector, optionally scoped to one
    cycle. Unchanged logic/shape - now built on correct per-member rows."""
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
        total_returned = Decimal('0.00')
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