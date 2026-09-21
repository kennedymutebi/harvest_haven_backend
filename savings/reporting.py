"""
savings/reporting.py

Delegates the B/F math to the tested domain layer (savings_domain/balance.py).
Public function names and return-dict shapes are kept stable on purpose.
"""

from decimal import Decimal

from django.db.models import Sum

from .models import SavingsCycle, SavingsEntry, Withdrawal
from .infrastructure import get_member_balance


def get_member_cycle_summary(member, cycle):
    """
    - opening_balance / carry_forward: Brought Forward as of this cycle's start.
    - savings / withdrawals: raw totals strictly within THIS cycle (gross
      activity — unaffected by FIFO allocation).
    - this_month: what actually REMAINS from this cycle's deposits after
      any withdrawal has drawn against them — the correct number for a
      "This Month" balance display. NEW — was missing before, which is
      why views.py had to fall back to the wrong field.
    - closing_balance: opening_balance + this_month = the member's real
      Total Balance right now.
    - returned_amount: equals closing_balance once the cycle is closed.
    """
    balance = get_member_balance(member.id, cycle)

    savings = SavingsEntry.objects.filter(
        member=member, cycle=cycle
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    withdrawals = Withdrawal.objects.filter(
        member=member, cycle=cycle
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    opening_balance = balance.brought_forward.amount
    this_month = balance.this_month.amount
    closing_balance = balance.total.amount
    returned_amount = closing_balance if cycle.status == 'closed' else Decimal('0.00')

    return {
        'member': member,
        'cycle': cycle,
        'opening_balance': opening_balance,
        'carry_forward': opening_balance,  # backward-compat alias
        'savings': savings,
        'withdrawals': withdrawals,
        'this_month': this_month,          # NEW
        'returned_amount': returned_amount,
        'closing_balance': closing_balance,
    }


def get_member_lifetime_history(member):
    cycle_ids = set(
        SavingsEntry.objects.filter(member=member).values_list('cycle_id', flat=True)
    ) | set(
        Withdrawal.objects.filter(member=member).exclude(cycle__isnull=True)
        .values_list('cycle_id', flat=True)
    )
    cycles = SavingsCycle.objects.filter(id__in=cycle_ids).order_by('-start_date')
    return [get_member_cycle_summary(member, cycle) for cycle in cycles]


def get_cycle_summary_for_all_members(cycle, members_queryset):
    return [get_member_cycle_summary(member, cycle) for member in members_queryset]


def get_collector_summary(collector, members_queryset, cycle=None):
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