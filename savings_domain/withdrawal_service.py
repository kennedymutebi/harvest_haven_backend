"""
Withdrawal planning: draws down a member's FULL lifetime pool of entries,
oldest deposit first (FIFO) - across ALL cycles, not just the active one.

This is the one deliberate behavior change from the current
CreateWithdrawalSerializer, which sums and allocates only within the
active cycle. Per client confirmation: a member should be able to
withdraw from their whole pot (Brought Forward + This Month combined);
the monthly charge is unaffected regardless of where the withdrawn money
came from (see profit_service.py).

This module only PLANS the withdrawal (which entries, how much from
each) - it does not touch a database. The infrastructure layer is
responsible for pulling entries in oldest-first order, calling `plan()`,
then persisting the resulting allocations inside a transaction (mirroring
the existing WithdrawalAllocation model, just without the cycle filter).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .balance import LedgerEntry
from .money import Money


class InsufficientBalanceError(Exception):
    def __init__(self, requested: Money, available: Money):
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient balance: requested {requested}, available {available}"
        )


@dataclass(frozen=True)
class Allocation:
    """One line of a withdrawal's FIFO draw-down plan against a single
    deposit entry - mirrors the existing WithdrawalAllocation model."""

    entry_id: int
    amount: Money


@dataclass(frozen=True)
class WithdrawalPlan:
    total_amount: Money
    allocations: List[Allocation]


class WithdrawalPlanner:
    def plan(self, amount: Money, entries_oldest_first: List[LedgerEntry]) -> WithdrawalPlan:
        """
        `entries_oldest_first` must already be sorted oldest -> newest by
        the caller, exactly like the existing
        `.order_by('date', 'created_at')` — just no longer filtered to a
        single cycle.
        """
        if amount.is_negative() or amount.is_zero():
            raise ValueError("Withdrawal amount must be greater than zero")

        available = Money.zero()
        for entry in entries_oldest_first:
            available = available + entry.remaining

        if amount > available:
            raise InsufficientBalanceError(requested=amount, available=available)

        remaining_to_withdraw = amount
        allocations: List[Allocation] = []

        for entry in entries_oldest_first:
            if remaining_to_withdraw.is_zero():
                break
            entry_remaining = entry.remaining
            if entry_remaining.is_zero():
                continue
            take = entry_remaining if entry_remaining < remaining_to_withdraw else remaining_to_withdraw
            allocations.append(Allocation(entry_id=entry.id, amount=take))
            remaining_to_withdraw = remaining_to_withdraw - take

        return WithdrawalPlan(total_amount=amount, allocations=allocations)