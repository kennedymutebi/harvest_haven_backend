"""
Lifetime balance calculation: Brought Forward / This Month / Total.

This replaces the mental model in the current savings/reporting.py, where
`get_member_cycle_summary()` explicitly computes `carry_forward` but never
adds it into `closing_balance` (opening_balance is hardcoded to zero,
"cycles are fully independent by design"). That is precisely the
"savings looks like it resets" bug described in Section 1 of the summary
doc — this module is the fix.

Design:
  - Brought Forward = money still remaining (not yet withdrawn) from
    entries belonging to any OLDER cycle.
  - This Month       = money still remaining from entries belonging to
    THIS cycle only.
  - Total            = Brought Forward + This Month.

Withdrawals never appear directly in this calculation. They are already
reflected as reduced `remaining` on whichever entries they were
FIFO-allocated against (see withdrawal_service.py) — which is exactly
what makes Brought Forward visibly shrink when a withdrawal eats into old
money, without a new deposit ever inflating it.

Zero Django imports. Pure dataclasses + plain functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List

from .money import Money


@dataclass(frozen=True)
class CycleRef:
    """Minimal, framework-independent stand-in for SavingsCycle."""

    id: int
    start_date: date
    status: str  # 'upcoming' | 'active' | 'closed'


@dataclass(frozen=True)
class LedgerEntry:
    """Minimal, framework-independent stand-in for SavingsEntry."""

    id: int
    cycle_id: int
    amount: Money
    withdrawn_amount: Money = Money.zero()

    @property
    def remaining(self) -> Money:
        return self.amount - self.withdrawn_amount


@dataclass(frozen=True)
class MemberBalance:
    brought_forward: Money
    this_month: Money

    @property
    def total(self) -> Money:
        return self.brought_forward + self.this_month


class BalanceCalculator:
    """Computes a member's B/F / This Month / Total for one cycle, given
    every entry that member has ever made (across all cycles)."""

    def calculate(
        self,
        entries: List[LedgerEntry],
        cycle: CycleRef,
        all_cycles: List[CycleRef],
    ) -> MemberBalance:
        cycles_by_id: Dict[int, CycleRef] = {c.id: c for c in all_cycles}

        brought_forward = Money.zero()
        this_month = Money.zero()

        for entry in entries:
            entry_cycle = cycles_by_id.get(entry.cycle_id)
            if entry_cycle is None:
                # Orphaned/unknown cycle reference — ignore defensively
                # rather than silently mis-bucketing real money.
                continue

            if entry.cycle_id == cycle.id:
                this_month = this_month + entry.remaining
            elif entry_cycle.start_date < cycle.start_date:
                brought_forward = brought_forward + entry.remaining
            # Entries whose cycle starts AFTER the requested cycle are
            # intentionally excluded from both buckets (this would only
            # happen for a "late entry" backdated oddly; it should not
            # count as this cycle's or an earlier cycle's money).

        return MemberBalance(brought_forward=brought_forward, this_month=this_month)