"""The YGOPRODeck provider: dump-backed, and therefore free.

Prices ship inside the same bulk ``cardinfo.php`` file the card attributes come
from, so once that dump is cached, valuing the entire collection costs zero
network requests. It is a local join, and it should feel like one.

The only per-row network work is the optional per-printing refinement, which
lives in ``refine.py`` — not here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

import duckdb

from ..config import DEFAULT_PRICE_FIELD
from ..money import Money
from .provider import PriceKey

__all__ = ["YgoprodeckProvider", "CURRENCY_BY_FIELD"]

#: The currency each dump field is quoted in. Getting this wrong is the single
#: easiest way to produce a confidently wrong total, so it lives in one dict.
CURRENCY_BY_FIELD: dict[str, str] = {
    "cardmarket_price": "EUR",
    "tcgplayer_price": "USD",
    "ebay_price": "USD",
    "amazon_price": "USD",
    "coolstuffinc_price": "USD",
}

_COLUMN_BY_FIELD = {
    "cardmarket_price": "cardmarket_price_eur",
    "tcgplayer_price": "tcgplayer_price_usd",
    "ebay_price": "ebay_price_usd",
    "amazon_price": "amazon_price_usd",
    "coolstuffinc_price": "coolstuffinc_price_usd",
}


class YgoprodeckProvider:
    """Reads the cached catalogue tables on an open connection.

    A run picks one ``source_field``, and therefore one currency, and says so.
    """

    name = "ygoprodeck"

    def __init__(
        self, con: duckdb.DuckDBPyConnection, source_field: str = DEFAULT_PRICE_FIELD
    ) -> None:
        if source_field not in CURRENCY_BY_FIELD:
            raise ValueError(
                f"Unknown price field {source_field!r}. Expected one of "
                f"{list(CURRENCY_BY_FIELD)}."
            )
        self._con = con
        self.source_field = source_field
        self.currency = CURRENCY_BY_FIELD[source_field]
        self._column = _COLUMN_BY_FIELD[source_field]

    # --- per-passcode --------------------------------------------------------

    def passcode_prices(self) -> dict[str, Money]:
        """Every owned passcode's price, in one query."""
        rows = self._con.execute(
            f"""
            SELECT DISTINCT c.passcode, p.{self._column}
            FROM collection_enriched c
            JOIN card_prices p ON p.card_id = c.card_id
            WHERE p.{self._column} IS NOT NULL
            """
        ).fetchall()
        return {r[0]: Money(r[1], self.currency) for r in rows}

    # --- per-printing --------------------------------------------------------

    def printing_prices(self) -> dict[PriceKey, Money]:
        """Owned (passcode, set_code) pairs the dump prices at printing grain.

        Only ~28% of printings carry a set_price, so this covers a minority —
        the rest fall back to the per-passcode number, which is correct
        behaviour, not a gap.

        set_price is USD on every path, so this is only meaningful for a USD
        source field. A EUR run gets nothing here and is per-passcode
        throughout.
        """
        if self.currency != "USD":
            return {}
        rows = self._con.execute(
            """
            SELECT DISTINCT c.passcode, c.set_code, s.set_price_usd
            FROM collection_enriched c
            JOIN card_sets s ON s.card_id = c.card_id AND s.set_code = c.set_code
            WHERE c.set_code IS NOT NULL AND s.set_price_usd IS NOT NULL
            """
        ).fetchall()
        return {(r[0], r[1]): Money(r[2], "USD") for r in rows}

    # --- the protocol --------------------------------------------------------

    def prices(self, keys: Sequence[PriceKey]) -> dict[PriceKey, Money | None]:
        """The real method. One local join, whatever the batch size."""
        by_printing = self.printing_prices()
        by_passcode = self.passcode_prices()
        out: dict[PriceKey, Money | None] = {}
        for key in keys:
            passcode, set_code = key
            # A known printing beats the per-passcode number; a row with no
            # set_code degrades to per-passcode rather than being dropped.
            if set_code is not None and key in by_printing:
                out[key] = by_printing[key]
            else:
                out[key] = by_passcode.get(passcode)
        return out

    def price(self, passcode: str, set_code: str | None = None) -> Money | None:
        return self.prices([(passcode, set_code)])[(passcode, set_code)]

    # --- buying, as opposed to valuing ---------------------------------------

    def market_low(self, card_ids: Sequence[str]) -> dict[str, Money]:
        """Per-card market low, for costing cards you do not own yet.

        Deliberately per-passcode and never per-printing. YGOPRODeck's
        per-passcode price is the market low across printings, which is what
        someone buying a playable copy pays; set_price exists for only ~28% of
        printings and that subset skews collectible, so costing a shopping list
        from it overstates the bill several-fold.
        """
        if not card_ids:
            return {}
        placeholders = ", ".join("?" * len(card_ids))
        rows = self._con.execute(
            f"SELECT card_id, {self._column} FROM card_prices "
            f"WHERE card_id IN ({placeholders}) AND {self._column} IS NOT NULL",
            list(card_ids),
        ).fetchall()
        return {r[0]: Money(Decimal(r[1]), self.currency) for r in rows}
