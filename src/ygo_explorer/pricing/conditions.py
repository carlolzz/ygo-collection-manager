"""Condition multipliers.

One table, one module, and clearly labelled: these are a heuristic, not a source
of truth. A Poor copy is not worth a Near Mint copy's price, but nor is the
exact discount knowable from YGOPRODeck's data — their prices approximate NM and
carry no grade at all.
"""

from __future__ import annotations

from decimal import Decimal

from ..collection.schema import CONDITIONS

__all__ = ["CONDITION_MULTIPLIERS", "UnknownCondition", "multiplier_for"]


class UnknownCondition(ValueError):
    """An unrecognized grade. Never silently treated as 1.0."""


# Heuristic, tune from real sales; not a source of truth.
# Cardmarket order, best to worst. Decimal so no multiplication touches a float.
CONDITION_MULTIPLIERS: dict[str, Decimal] = {
    "MINT": Decimal("1.05"),
    "NEAR_MINT": Decimal("1.00"),  # the reference grade — YGOPRODeck prices approximate NM
    "EXCELLENT": Decimal("0.90"),
    "GOOD": Decimal("0.75"),
    "LIGHT_PLAYED": Decimal("0.65"),
    "PLAYED": Decimal("0.50"),
    "POOR": Decimal("0.40"),
}

# Edition moves price in reality too, but by an amount that varies wildly per
# card. It is surfaced in the breakdown and deliberately left unmodelled rather
# than guessed at — there is no EDITION_MULTIPLIERS, and that is intentional.

assert set(CONDITION_MULTIPLIERS) == set(CONDITIONS), (
    "the multiplier table and the condition enum must not drift apart"
)


def multiplier_for(condition: str) -> Decimal:
    """The multiplier for a grade. An unknown grade is an error."""
    try:
        return CONDITION_MULTIPLIERS[condition]
    except KeyError:
        raise UnknownCondition(
            f"No multiplier for condition {condition!r}. Expected one of "
            f"{list(CONDITION_MULTIPLIERS)}."
        ) from None
