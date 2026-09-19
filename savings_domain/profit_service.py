"""
Per-member monthly profit (charge) calculation.

Replaces SavingsCycle.total_profit(), which charges the whole SACCO
`interest_rate`% of everyone's combined deposits for the cycle - a single
cycle-wide percentage, not tied to any individual member.

Per client confirmation, the new rule is:
  - charge is calculated PER MEMBER
  - based only on that member's RAW deposited amount this month
    (entry.amount, never entry.remaining / withdrawn_amount)
  - withdrawals - even same-month ones - never reduce the charge

This directly enables the new "profit per member" API the client asked
for: `calculate_for_all()` returns one line per member.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .balance import LedgerEntry
from .charge_policy import TieredChargePolicy
from .money import Money


@dataclass(frozen=True)
class MemberProfitLine:
    member_id: int
    collected_this_month: Money
    charge: Money


class MemberProfitCalculator:
    def __init__(self, policy: TieredChargePolicy):
        self.policy = policy

    def calculate_for_member(
        self, member_id: int, this_month_entries: List[LedgerEntry]
    ) -> MemberProfitLine:
        collected = Money.zero()
        for entry in this_month_entries:
            # Deliberately entry.amount, NOT entry.remaining: a
            # withdrawal made later in the same month must not lower
            # what this member is charged for having collected it.
            collected = collected + entry.amount

        charge = self.policy.charge_for(collected)
        return MemberProfitLine(
            member_id=member_id, collected_this_month=collected, charge=charge
        )

    def calculate_for_all(
        self, entries_by_member: Dict[int, List[LedgerEntry]]
    ) -> List[MemberProfitLine]:
        return [
            self.calculate_for_member(member_id, entries)
            for member_id, entries in entries_by_member.items()
        ]

    @staticmethod
    def total_profit(lines: List[MemberProfitLine]) -> Money:
        """Sum of every member's individual charge - this is what the
        dashboard's 'Total Profit' figure should become (see the open
        question in Section 8 about lifetime vs this-month; this gives
        this-month, summed across members)."""
        total = Money.zero()
        for line in lines:
            total = total + line.charge
        return total