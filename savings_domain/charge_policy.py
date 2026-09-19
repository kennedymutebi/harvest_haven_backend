"""
Tiered monthly-charge ("profit") policy — Section 7 of the Sacco System
Upgrade summary, client-confirmed as final.

This charge is based ONLY on how much a member personally deposited in a
given month. It is completely separate from balances and withdrawals:
withdrawing money in the same month a deposit was made does NOT reduce
the charge (see profit_service.py for where that rule is enforced).

Client-confirmed defaults for the 3 edge cases flagged in the original
doc's note (bands are final, but the doc explicitly left these open):

  1. Amount falls in a GAP between two bands (e.g. exactly 65,000,
     between the 60,000 and 70,000 boundaries) -> rounds UP to the
     next band. Chosen so the SACCO is never under-charged.
  2. Amount below the lowest band (< 2,000)     -> no charge.
  3. Amount above the highest band (> 1,000,000) -> the top band's
     fee (20,000) continues to apply; no higher band exists yet.

All three are isolated in `TieredChargePolicy` so they can be changed
later (e.g. loaded from a database config table, per Section 7's closing
paragraph) without touching any other code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .money import Money


@dataclass(frozen=True)
class ChargeBand:
    min_amount: Money
    max_amount: Optional[Money]  # None = open-ended top band
    fee: Money

    def covers(self, amount: Money) -> bool:
        if amount < self.min_amount:
            return False
        if self.max_amount is None:
            return True
        return amount <= self.max_amount


# The exact table from Section 7, client-confirmed.
DEFAULT_CHARGE_BANDS: List[ChargeBand] = [
    ChargeBand(Money("2000"), Money("60000"), Money("2000")),
    ChargeBand(Money("70000"), Money("90000"), Money("3000")),
    ChargeBand(Money("100000"), Money("120000"), Money("4000")),
    ChargeBand(Money("130000"), Money("150000"), Money("5000")),
    ChargeBand(Money("160000"), Money("300000"), Money("7000")),
    ChargeBand(Money("310000"), Money("600000"), Money("10000")),
    ChargeBand(Money("610000"), Money("900000"), Money("15000")),
    ChargeBand(Money("910000"), Money("1000000"), Money("20000")),
]


class TieredChargePolicy:
    """Given a member's total collection for a month, returns the flat fee."""

    def __init__(self, bands: Optional[List[ChargeBand]] = None):
        self.bands: List[ChargeBand] = sorted(
            bands or DEFAULT_CHARGE_BANDS, key=lambda b: b.min_amount.amount
        )
        if not self.bands:
            raise ValueError("TieredChargePolicy requires at least one band")

    def charge_for(self, collected_this_month: Money) -> Money:
        if collected_this_month.is_negative():
            raise ValueError("Collected amount cannot be negative")

        lowest_band = self.bands[0]
        if collected_this_month < lowest_band.min_amount:
            return Money.zero()  # edge case 2: below lowest band

        for band in self.bands:
            if band.covers(collected_this_month):
                return band.fee  # exact match within a defined band

        top_band = self.bands[-1]
        if top_band.max_amount is not None and collected_this_month > top_band.max_amount:
            return top_band.fee  # edge case 3: above highest band

        # edge case 1: sits in a gap between two bands -> round up
        for band in self.bands:
            if collected_this_month < band.min_amount:
                return band.fee

        return top_band.fee  # defensive fallback, should not normally reach here