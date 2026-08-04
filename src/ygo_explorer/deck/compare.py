"""Compare a deck against the collection, and cost what is missing.

Two counting decisions that everything else follows from:

- **Demand is aggregated across main, extra and side.** You need the physical
  copies at the same time — a list running 2 Mystical Space Typhoon in the main
  and 1 in the side needs three cards, not two and one.
- **Ownership matches on ``card_id``, not passcode.** A Dark Magician is a Dark
  Magician whatever the artwork, and the catalogue already maps alternate-art
  passcodes back to their card. Cards the dump has never heard of fall back to
  matching on the passcode itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from ..config import DEFAULT_PRICE_FIELD
from ..money import Money, sum_money
from ..pricing.ygoprodeck import YgoprodeckProvider
from .parse import ZONES, Deck
from .resolve import Resolution, resolve_deck

__all__ = ["DeckCard", "DeckAnalysis", "analyze_deck"]


@dataclass(frozen=True)
class DeckCard:
    card_id: str
    passcode: str
    name: str
    needed: int
    owned: int
    missing: int
    zones: dict[str, int]
    unit_price: Money | None
    subtotal: Money | None

    @property
    def is_priced(self) -> bool:
        return self.unit_price is not None


@dataclass
class DeckAnalysis:
    source_format: str
    currency: str
    cards: list[DeckCard] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    zone_counts: dict[str, int] = field(default_factory=dict)

    total_needed: int = 0
    total_owned: int = 0
    total_missing: int = 0
    distinct_missing: int = 0
    unpriced_missing_cards: int = 0
    estimated_cost: Money | None = None

    @property
    def caveat(self) -> str:
        parts = [
            f"Estimate in {self.currency}, at each card's lowest market price "
            "across printings: the price of a playable copy, not of any "
            "particular printing or rarity."
        ]
        if self.unpriced_missing_cards:
            parts.append(
                f"{self.unpriced_missing_cards} missing card(s) have no price and "
                "contribute nothing to the total."
            )
        if self.unresolved:
            parts.append(
                f"{len(self.unresolved)} line(s) matched no card and were left out."
            )
        return " ".join(parts)


_OWNED = """
SELECT card_id, passcode, SUM(quantity)::BIGINT AS copies
FROM collection_enriched
GROUP BY card_id, passcode
"""


def _owned_counts(con: duckdb.DuckDBPyConnection) -> tuple[dict[str, int], dict[str, int]]:
    """Copies owned, keyed by card_id and (for dumpless rows) by passcode."""
    by_card: dict[str, int] = {}
    by_passcode: dict[str, int] = {}
    for card_id, passcode, copies in con.execute(_OWNED).fetchall():
        if card_id is not None:
            by_card[card_id] = by_card.get(card_id, 0) + copies
        by_passcode[passcode] = by_passcode.get(passcode, 0) + copies
    return by_card, by_passcode


def analyze_deck(
    con: duckdb.DuckDBPyConnection,
    deck: Deck,
    *,
    source_field: str = DEFAULT_PRICE_FIELD,
    resolution: Resolution | None = None,
) -> DeckAnalysis:
    """What the deck needs, what is owned, and what the shortfall would cost."""
    resolution = resolution or resolve_deck(con, deck)
    provider = YgoprodeckProvider(con, source_field)

    # Aggregate demand per card across all three zones.
    demand: dict[str, dict] = {}
    for entry in resolution.resolved:
        card = demand.setdefault(
            entry.card_id,
            {
                "passcode": entry.passcode,
                "name": entry.name,
                "needed": 0,
                "zones": dict.fromkeys(ZONES, 0),
            },
        )
        card["needed"] += entry.quantity
        card["zones"][entry.zone] += entry.quantity

    owned_by_card, owned_by_passcode = _owned_counts(con)
    prices = provider.market_low(list(demand))

    analysis = DeckAnalysis(
        source_format=deck.source_format,
        currency=provider.currency,
        unresolved=resolution.unresolved_labels,
        zone_counts=deck.zone_counts(),
    )

    for card_id, info in demand.items():
        owned = owned_by_card.get(card_id, owned_by_passcode.get(info["passcode"], 0))
        missing = max(0, info["needed"] - owned)
        unit = prices.get(card_id)
        subtotal = (unit * missing).rounded() if unit is not None and missing else None

        analysis.cards.append(
            DeckCard(
                card_id=card_id,
                passcode=info["passcode"],
                name=info["name"],
                needed=info["needed"],
                owned=owned,
                missing=missing,
                zones=info["zones"],
                unit_price=unit,
                subtotal=subtotal,
            )
        )

        analysis.total_needed += info["needed"]
        # Only the copies the deck actually uses count as "owned for this deck";
        # a spare fourth copy is not progress towards a three-of.
        analysis.total_owned += min(owned, info["needed"])
        analysis.total_missing += missing
        if missing:
            analysis.distinct_missing += 1
            if unit is None:
                analysis.unpriced_missing_cards += 1

    analysis.cards.sort(key=lambda c: (-c.missing, c.name.casefold()))
    analysis.estimated_cost = sum_money(
        (c.subtotal for c in analysis.cards), provider.currency
    ).rounded()
    return analysis
