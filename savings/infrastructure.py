"""
savings/infrastructure.py

The ONLY place allowed to import both Django models AND the domain layer.
Converts ORM rows into plain domain objects (CycleRef, LedgerEntry), calls
the pure domain logic, and converts results back into whatever the ORM
needs to persist. Nothing in savings_domain/ ever imports Django; nothing
here contains business rules - it's purely translation + persistence.
"""

from decimal import Decimal
from typing import Dict, List

from django.db import transaction

from savings.models import SavingsCycle, SavingsEntry, Withdrawal, WithdrawalAllocation
from savings_domain.balance import BalanceCalculator, CycleRef, LedgerEntry, MemberBalance
from savings_domain.charge_policy import TieredChargePolicy
from savings_domain.money import Money
from savings_domain.profit_service import MemberProfitCalculator, MemberProfitLine
from savings_domain.withdrawal_service import WithdrawalPlanner, WithdrawalPlan


# ---------------------------------------------------------------------------
# ORM  ->  domain object translation
# ---------------------------------------------------------------------------

def _to_cycle_ref(cycle: SavingsCycle) -> CycleRef:
    return CycleRef(id=cycle.id, start_date=cycle.start_date, status=cycle.status)


def _all_cycle_refs() -> List[CycleRef]:
    return [_to_cycle_ref(c) for c in SavingsCycle.objects.all()]


def _to_ledger_entry(entry: SavingsEntry) -> LedgerEntry:
    return LedgerEntry(
        id=entry.id,
        cycle_id=entry.cycle_id,
        amount=Money(entry.amount),
        withdrawn_amount=Money(entry.withdrawn_amount),
    )


def _member_entries_oldest_first(member_id: int) -> List[SavingsEntry]:
    """Every entry this member has EVER made, across every cycle, oldest
    first. This is the query that changes from the old
    CreateWithdrawalSerializer - no `.filter(cycle=active_cycle)` here."""
    return list(
        SavingsEntry.objects.select_for_update()
        .filter(member_id=member_id)
        .order_by('date', 'created_at')
    )


# ---------------------------------------------------------------------------
# Balance: Brought Forward / This Month / Total
# ---------------------------------------------------------------------------

def get_member_balance(member_id: int, cycle: SavingsCycle) -> MemberBalance:
    """Replaces the opening_balance=0 / unused-carry_forward logic in the
    old savings/reporting.py."""
    entries = SavingsEntry.objects.filter(member_id=member_id)
    ledger_entries = [_to_ledger_entry(e) for e in entries]
    all_cycles = _all_cycle_refs()
    cycle_ref = _to_cycle_ref(cycle)

    return BalanceCalculator().calculate(ledger_entries, cycle_ref, all_cycles)


# ---------------------------------------------------------------------------
# Withdrawal: lifetime FIFO pool, not cycle-scoped
# ---------------------------------------------------------------------------

class InsufficientBalanceForWithdrawal(Exception):
    def __init__(self, requested: Decimal, available: Decimal):
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient balance. Requested {requested}, available {available}."
        )


@transaction.atomic
def execute_withdrawal(
    *, member_id: int, cycle: SavingsCycle, amount: Decimal, date, reason: str, created_by
) -> Withdrawal:
    """
    Creates a Withdrawal record and its WithdrawalAllocation rows, drawing
    FIFO across the member's ENTIRE lifetime pool of entries (not just the
    given cycle). `cycle` here only tags WHEN the withdrawal happened, for
    reporting purposes - it no longer limits which deposits it can draw
    from.
    """
    entries = _member_entries_oldest_first(member_id)
    ledger_entries = [_to_ledger_entry(e) for e in entries]
    entries_by_id = {e.id: e for e in entries}

    planner = WithdrawalPlanner()
    try:
        plan: WithdrawalPlan = planner.plan(Money(amount), ledger_entries)
    except Exception as exc:
        from savings_domain.withdrawal_service import InsufficientBalanceError
        if isinstance(exc, InsufficientBalanceError):
            raise InsufficientBalanceForWithdrawal(
                requested=exc.requested.amount, available=exc.available.amount
            ) from exc
        raise

    withdrawal = Withdrawal.objects.create(
        member_id=member_id,
        cycle=cycle,
        amount=amount,
        date=date,
        reason=reason or 'Withdraw to be refilled',
        created_by=created_by,
    )

    for allocation in plan.allocations:
        entry = entries_by_id[allocation.entry_id]
        entry.withdrawn_amount = entry.withdrawn_amount + allocation.amount.amount
        entry.save(update_fields=['withdrawn_amount', 'updated_at'])
        WithdrawalAllocation.objects.create(
            withdrawal=withdrawal,
            savings_entry=entry,
            amount=allocation.amount.amount,
        )

    return withdrawal


def get_available_balance(member_id: int) -> Decimal:
    """Lifetime available balance across ALL cycles - what the withdrawal
    validation should check against now, instead of only the active
    cycle's total."""
    entries = SavingsEntry.objects.filter(member_id=member_id)
    total = Money.zero()
    for entry in entries:
        total = total + (Money(entry.amount) - Money(entry.withdrawn_amount))
    return total.amount


# ---------------------------------------------------------------------------
# Profit: per-member tiered charge
# ---------------------------------------------------------------------------

def get_member_profit_for_cycle(member_id: int, cycle: SavingsCycle) -> MemberProfitLine:
    entries = SavingsEntry.objects.filter(member_id=member_id, cycle=cycle)
    ledger_entries = [_to_ledger_entry(e) for e in entries]
    calculator = MemberProfitCalculator(TieredChargePolicy())
    return calculator.calculate_for_member(member_id, ledger_entries)


def get_all_member_profits_for_cycle(cycle: SavingsCycle) -> List[MemberProfitLine]:
    """Backbone of the new 'profit per member' API the client asked for."""
    entries = SavingsEntry.objects.filter(cycle=cycle).only(
        'id', 'member_id', 'cycle_id', 'amount', 'withdrawn_amount'
    )

    entries_by_member: Dict[int, List[LedgerEntry]] = {}
    for entry in entries:
        entries_by_member.setdefault(entry.member_id, []).append(_to_ledger_entry(entry))

    calculator = MemberProfitCalculator(TieredChargePolicy())
    return calculator.calculate_for_all(entries_by_member)


def get_cycle_total_profit(cycle: SavingsCycle) -> Decimal:
    """
    Sum of every member's individual tiered charge for this cycle.

    This is what SavingsCycleSerializer.get_total_profit() should call
    now, replacing SavingsCycle.total_profit() (interest_rate% of the
    whole cycle's deposits, cycle-wide, not per-member). Kept here rather
    than in serializers.py so serializers.py never has to import the
    domain layer directly - only this infrastructure module does.
    """
    lines = get_all_member_profits_for_cycle(cycle)
    return MemberProfitCalculator.total_profit(lines).amount
def get_balances_for_members(member_ids: List[int], cycle: SavingsCycle) -> Dict[int, MemberBalance]:
    """Bulk version of get_member_balance: ONE query for all cycles, ONE
    query for every entry across all given members, then pure-Python
    balance math per member (no further DB hits). This is what
    MembersListWithSavingsView should use so showing B/F + This Month +
    Total for a whole list still costs 2 queries total, not 2 per member."""
    all_cycles = _all_cycle_refs()
    cycle_ref = _to_cycle_ref(cycle)

    entries = SavingsEntry.objects.filter(member_id__in=member_ids)
    entries_by_member: Dict[int, List[LedgerEntry]] = {}
    for entry in entries:
        entries_by_member.setdefault(entry.member_id, []).append(_to_ledger_entry(entry))

    calculator = BalanceCalculator()
    return {
        member_id: calculator.calculate(entries_by_member.get(member_id, []), cycle_ref, all_cycles)
        for member_id in member_ids
    }