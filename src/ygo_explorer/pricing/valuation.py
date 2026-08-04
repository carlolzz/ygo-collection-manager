"""Valuing owned rows.

Every price goes through the snapshot store on the way, so a total is always
re-explainable afterwards and the history exists whether or not anyone asks for
it yet.

The result carries the caveats the UI is required to show next to the number:
that it is an estimate, how many rows were priced per-printing versus
per-passcode, how many could not be priced, the currency, and how old the data
is. A confidently wrong total is worse than an obviously approximate one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

import duckdb

from ..config import DEFAULT_PRICE_FIELD
from ..money import Money
from .conditions import multiplier_for
from .provider import PriceKey
from .snapshots import STATUS_OK, STATUS_UNAVAILABLE, SnapshotStore
from .ygoprodeck import YgoprodeckProvider

__all__ = ["ValuedRow", "Valuation", "value_rows"]

PER_PRINTING = "per_printing"
PER_PASSCODE = "per_passcode"
UNPRICED = "unpriced"


@dataclass(frozen=True)
class ValuedRow:
    """One collection row, valued. Quantity and condition are applied here."""

    passcode: str
    name: str
    set_code: str | None
    set_name: str | None
    rarity: str | None
    condition: str
    edition: str
    language: str
    quantity: int
    basis: str  # PER_PRINTING | PER_PASSCODE | UNPRICED
    unit_price: Money | None
    multiplier: Decimal
    subtotal: Money | None


@dataclass
class Valuation:
    currency: str
    provider: str
    source_field: str
    total: Money
    rows: list[ValuedRow] = field(default_factory=list)
    per_printing_rows: int = 0
    per_passcode_rows: int = 0
    unpriced_rows: int = 0
    unpriced_copies: int = 0
    priced_at: datetime | None = None

    @property
    def is_estimate(self) -> bool:
        """Always true, and said out loud.

        YGOPRODeck's card_prices are per passcode, not per printing or rarity,
        so a Secret Rare and a Common of the same card get the same number
        unless a set_price landed for that printing.
        """
        return True

    @property
    def caveat(self) -> str:
        parts = [
            f"Estimate in {self.currency}.",
            f"{self.per_printing_rows} row(s) priced for their specific printing, "
            f"{self.per_passcode_rows} priced per card (so rarity is not reflected)",
        ]
        if self.unpriced_rows:
            parts.append(
                f"{self.unpriced_rows} row(s) ({self.unpriced_copies} copies) could "
                "not be priced at all and contribute nothing to the total"
            )
        return "; ".join(parts) + "."


_ROWS = """
SELECT passcode, name, set_code, set_name, rarity, condition, edition, language,
       quantity
FROM collection_enriched
"""


def value_rows(
    con: duckdb.DuckDBPyConnection,
    store: SnapshotStore,
    *,
    source_field: str = DEFAULT_PRICE_FIELD,
    passcode: str | None = None,
) -> Valuation:
    """Value the whole collection, or one card's rows.

    Zero network requests: the prices are already in the cached dump, so this is
    a local join plus a condition multiplier. It should complete in well under a
    second on a few thousand rows — and so must not show a progress bar
    pretending otherwise.
    """
    provider = YgoprodeckProvider(con, source_field)
    currency = provider.currency

    sql = _ROWS + (" WHERE passcode = ?" if passcode else "")
    raw = con.execute(sql, [passcode] if passcode else []).fetchall()

    by_printing = provider.printing_prices()
    by_passcode = provider.passcode_prices()

    result = Valuation(
        currency=currency,
        provider=provider.name,
        source_field=source_field,
        total=Money.zero(currency),
    )

    for (pc, name, set_code, set_name, rarity, condition, edition,
         language, quantity) in raw:
        key: PriceKey = (pc, set_code)

        if set_code is not None and key in by_printing:
            unit, basis = by_printing[key], PER_PRINTING
        elif pc in by_passcode:
            # Rows with no set_code land here. They are valued, not excluded.
            unit, basis = by_passcode[pc], PER_PASSCODE
        else:
            unit, basis = None, UNPRICED

        # Every price observation is recorded, including the absences — that is
        # what makes a later "why was this row zero?" answerable.
        store.record(
            key,
            provider=provider.name,
            currency=currency,
            source_field=source_field,
            amount=unit.amount if unit else None,
            status=STATUS_OK if unit else STATUS_UNAVAILABLE,
            detail=basis,
        )

        multiplier = multiplier_for(condition)
        subtotal = (unit * multiplier * quantity).rounded() if unit else None

        result.rows.append(
            ValuedRow(
                passcode=pc,
                name=name,
                set_code=set_code,
                set_name=set_name,
                rarity=rarity,
                condition=condition,
                edition=edition,
                language=language,
                quantity=quantity,
                basis=basis,
                unit_price=unit,
                multiplier=multiplier,
                subtotal=subtotal,
            )
        )

        if basis == PER_PRINTING:
            result.per_printing_rows += 1
        elif basis == PER_PASSCODE:
            result.per_passcode_rows += 1
        else:
            result.unpriced_rows += 1
            result.unpriced_copies += quantity

        if subtotal is not None:
            result.total = result.total + subtotal

    result.total = result.total.rounded()
    result.priced_at = store.newest_fetched_at(provider.name, source_field)
    store.flush()
    return result
