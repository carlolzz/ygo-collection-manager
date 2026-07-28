"""Money with an explicit currency.

YGOPRODeck mixes currencies inside a single response — ``cardmarket_price`` is
EUR while ``tcgplayer_price``, ``ebay_price``, ``amazon_price`` and
``coolstuffinc_price`` are USD. Summing across them produces a confidently wrong
total, which is worse than an obviously approximate one. So there is no bare
amount anywhere in this app: every figure carries the currency it is quoted in,
and adding two different currencies raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

__all__ = ["Money", "CurrencyMismatch", "sum_money"]

_CENTS = Decimal("0.01")


class CurrencyMismatch(ValueError):
    """Raised on any attempt to combine two currencies without an FX rate."""


@dataclass(frozen=True, order=False)
class Money:
    """An amount in a named currency. Decimal throughout; never float."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError(
                f"Money.amount must be Decimal, got {type(self.amount).__name__}. "
                "Floats lose cents; parse from the string form instead."
            )
        if not self.currency:
            raise ValueError("Money requires an explicit currency")

    @classmethod
    def parse(cls, amount: str | Decimal | int | None, currency: str) -> "Money | None":
        """Build from the text form prices arrive in. None stays None."""
        if amount is None or amount == "":
            return None
        return cls(Decimal(str(amount)), currency)

    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(Decimal("0"), currency)

    def _check(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(
                f"Cannot combine {self.currency} and {other.currency}. Present them "
                "side by side, or convert through an explicit, dated FX rate stored "
                "with the result — an implicit 1:1 is forbidden."
            )

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Decimal | int) -> "Money":
        if isinstance(factor, float):
            raise TypeError(
                "Multiply Money by Decimal or int, not float — use "
                "Decimal(str(factor)) so the multiplier is exact."
            )
        return Money(self.amount * Decimal(factor), self.currency)

    __rmul__ = __mul__

    def rounded(self) -> "Money":
        """To the minor unit, half-up — the rounding a price tag uses."""
        return Money(self.amount.quantize(_CENTS, rounding=ROUND_HALF_UP), self.currency)

    def __str__(self) -> str:
        return f"{self.rounded().amount} {self.currency}"


def sum_money(items: Iterable[Money | None], currency: str) -> Money:
    """Total a mixed bag, skipping the unpriced. Raises on a foreign currency."""
    total = Money.zero(currency)
    for item in items:
        if item is not None:
            total = total + item
    return total
