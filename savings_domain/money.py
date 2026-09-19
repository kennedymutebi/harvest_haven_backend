"""
Money value object.

The current codebase does `float(some_decimal)` everywhere at the API
boundary (serializers, views). That's fine for JSON output, but doing
arithmetic in float anywhere (e.g. `total * (interest_rate / 100)`) risks
silent rounding errors with real currency. This class keeps all internal
math in Decimal, and only ever converts to float at the very last step,
explicitly, via `.to_float()`.

This file has ZERO Django/DRF imports. It can be unit tested with plain
`python -m unittest`, no database, no settings module.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Union

Number = Union[int, float, str, Decimal, "Money"]


class Money:
    """Immutable shilling amount, always rounded to 2 decimal places."""

    __slots__ = ("_amount",)

    def __init__(self, amount: Number = "0"):
        if isinstance(amount, Money):
            amount = amount._amount
        try:
            decimal_amount = Decimal(str(amount))
        except Exception as exc:  # noqa: BLE001 - re-raise with clearer message
            raise ValueError(f"Cannot create Money from {amount!r}") from exc
        self._amount = decimal_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def amount(self) -> Decimal:
        return self._amount

    # ---- arithmetic -------------------------------------------------
    def __add__(self, other: Number) -> "Money":
        return Money(self._amount + Money(other)._amount)

    def __radd__(self, other: Number) -> "Money":
        return self.__add__(other)

    def __sub__(self, other: Number) -> "Money":
        return Money(self._amount - Money(other)._amount)

    def __neg__(self) -> "Money":
        return Money(-self._amount)

    # ---- comparisons --------------------------------------------------
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (Money, int, float, str, Decimal)):
            return NotImplemented
        return self._amount == Money(other)._amount

    def __lt__(self, other: Number) -> bool:
        return self._amount < Money(other)._amount

    def __le__(self, other: Number) -> bool:
        return self._amount <= Money(other)._amount

    def __gt__(self, other: Number) -> bool:
        return self._amount > Money(other)._amount

    def __ge__(self, other: Number) -> bool:
        return self._amount >= Money(other)._amount

    def __hash__(self) -> int:
        return hash(self._amount)

    def __repr__(self) -> str:
        return f"Money('{self._amount}')"

    def __str__(self) -> str:
        return f"{self._amount:,.2f}"

    # ---- convenience ----------------------------------------------------
    def is_zero(self) -> bool:
        return self._amount == 0

    def is_negative(self) -> bool:
        return self._amount < 0

    @classmethod
    def zero(cls) -> "Money":
        return cls("0")

    def to_float(self) -> float:
        """Only use at the API/JSON boundary. Never chain further math on
        the result of this — always do math on Money objects."""
        return float(self._amount)