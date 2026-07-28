"""Response shapes.

Count fields are named for exactly which count they are. There is no field
called ``count``: the difference between "how many copies" and "how many
distinct cards" is the single easiest thing to get wrong here, so no label is
allowed to be ambiguous about it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "CardSummary",
    "CardPage",
    "OwnedRow",
    "CataloguePrinting",
    "CardDetail",
    "Bucket",
    "TimeBucket",
    "Stats",
    "FilterOptions",
    "CatalogueStatus",
    "CollectionStatus",
    "MoneyOut",
    "ValuedRowOut",
    "ValuationOut",
    "RefineJobOut",
    "DeckCardOut",
    "DeckAnalysisOut",
]


class CardSummary(BaseModel):
    """One distinct card, with ownership rolled up over the matching rows."""

    passcode: str = Field(description="Always a string; leading zeros are real.")
    name: str
    in_catalogue: bool = Field(
        description="False when the dump has no entry; attributes below are then unknown."
    )
    type: str | None = None
    frame_type: str | None = None
    attribute: str | None = None
    race: str | None = None
    archetype: str | None = None
    atk: int | None = None
    defense: int | None = None
    level: int | None = None
    source_image_url: str | None = Field(
        default=None,
        description=(
            "Upstream artwork URL, for the local image cache to download once. "
            "Not for the browser to load directly — YGOPRODeck's guide forbids "
            "hotlinking and blacklists IPs that do it."
        ),
    )
    total_copies: int = Field(description="SUM(quantity) over the matching rows.")
    row_count: int = Field(description="How many collection rows matched.")
    printing_count: int = Field(description="Distinct non-empty set_codes matched.")
    first_acquired_at: datetime | None = None


class CardPage(BaseModel):
    """A page of cards, plus totals for the whole filtered set.

    ``total_cards`` and ``total_copies`` describe every match, not just this
    page, and both reflect the active filters — so a condition filter reports
    the copies in that condition rather than the whole stack.
    """

    items: list[CardSummary]
    total_cards: int = Field(description="COUNT(DISTINCT passcode) over the matches.")
    total_copies: int = Field(description="SUM(quantity) over the matches.")
    limit: int
    offset: int


class OwnedRow(BaseModel):
    """One collection row: a stack of identical copies."""

    set_code: str | None = None
    set_name: str | None = None
    rarity: str | None = None
    condition: str
    edition: str
    language: str
    quantity: int
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class CataloguePrinting(BaseModel):
    """A printing the catalogue knows of, owned or not."""

    set_code: str | None = None
    set_name: str | None = None
    set_rarity: str | None = None
    set_price_usd: float | None = Field(
        default=None,
        description="Per-printing price, USD. There is no EUR equivalent at this grain.",
    )
    owned: bool = Field(description="Whether the collection holds this printing.")


class CardDetail(CardSummary):
    description: str | None = None
    rows: list[OwnedRow] = Field(description="Every owned row, best condition first.")
    printings: list[CataloguePrinting] = Field(
        description="Catalogue printings, the owned ones flagged."
    )


class Bucket(BaseModel):
    key: str | None
    total_copies: int
    distinct_cards: int


class TimeBucket(BaseModel):
    period: str
    total_copies: int
    distinct_cards: int


class Stats(BaseModel):
    total_copies: int = Field(description="SUM(quantity) over the whole collection.")
    distinct_cards: int = Field(description="COUNT(DISTINCT passcode).")
    collection_rows: int
    sets_represented: int = Field(description="Distinct non-empty set_names.")
    copies_without_printing: int = Field(
        description="Copies whose row has no set_code. Included in total_copies."
    )
    by_condition: list[Bucket]
    by_edition: list[Bucket]
    by_language: list[Bucket]
    by_type: list[Bucket]
    by_attribute: list[Bucket]
    by_archetype: list[Bucket]
    by_set: list[Bucket]
    acquisitions_by_month: list[TimeBucket]
    most_held: list[CardSummary] = Field(description="The long tail, most copies first.")


class FilterOptions(BaseModel):
    """Distinct values present in the collection, for building the filter bar."""

    condition: list[str]
    edition: list[str]
    language: list[str]
    rarity: list[str]
    set_name: list[str]
    type: list[str]
    frame_type: list[str]
    attribute: list[str]
    race: list[str]
    archetype: list[str]
    level_min: int | None = None
    level_max: int | None = None


class MoneyOut(BaseModel):
    """An amount that always states its currency. Serialized as a string so no
    JSON float ever rounds a price."""

    amount: str
    currency: str

    @classmethod
    def of(cls, money) -> "MoneyOut | None":
        if money is None:
            return None
        rounded = money.rounded()
        return cls(amount=str(rounded.amount), currency=rounded.currency)


class ValuedRowOut(BaseModel):
    passcode: str
    name: str
    set_code: str | None = None
    set_name: str | None = None
    rarity: str | None = None
    condition: str
    edition: str = Field(
        description="Surfaced, but deliberately not priced — edition moves value "
        "in reality by an amount that varies too much per card to guess."
    )
    language: str
    quantity: int
    basis: str = Field(description="per_printing | per_passcode | unpriced")
    unit_price: MoneyOut | None = None
    multiplier: str = Field(description="Condition multiplier. A heuristic.")
    subtotal: MoneyOut | None = None


class ValuationOut(BaseModel):
    """A valuation, with the caveats attached to the number rather than footnoted."""

    total: MoneyOut
    currency: str
    provider: str
    source_field: str
    is_estimate: bool = True
    caveat: str = Field(description="Plain words, shown next to the total.")
    per_printing_rows: int
    per_passcode_rows: int
    unpriced_rows: int
    unpriced_copies: int
    price_data_age_days: float | None = None
    rows: list[ValuedRowOut]


class RefineJobOut(BaseModel):
    """Progress of the per-printing refinement job."""

    id: str
    status: str = Field(description="pending | running | cancelled | finished | error")
    done: int
    total: int
    current_set_code: str | None = None
    refined: int
    unavailable: int
    failed: int
    skipped_fresh: int = Field(description="Keys with a fresh snapshot, not re-fetched.")
    errors: list[str] = []


class DeckCardOut(BaseModel):
    passcode: str
    name: str
    needed: int = Field(description="Copies the list calls for, across all zones.")
    owned: int = Field(description="Copies owned, any printing, condition or language.")
    missing: int
    zones: dict[str, int]
    unit_price: MoneyOut | None = None
    subtotal: MoneyOut | None = None


class DeckAnalysisOut(BaseModel):
    source_format: str = Field(description="ydke | ydk | plaintext")
    currency: str
    zone_counts: dict[str, int]
    total_needed: int
    total_owned: int
    total_missing: int
    distinct_missing: int
    unpriced_missing_cards: int
    estimated_cost: MoneyOut | None = None
    caveat: str
    unresolved: list[str] = Field(
        default_factory=list,
        description="Lines that matched no card. Reported, never silently dropped.",
    )
    cards: list[DeckCardOut]


class CollectionStatus(BaseModel):
    """Whether an export is loaded at all — the app runs without one."""

    has_collection: bool
    csv_path: str | None = None
    collection_rows: int = 0
    message: str


class CatalogueStatus(BaseModel):
    fetched_at: datetime | None = None
    age_days: float | None = None
    catalogue_cards: int
    catalogue_passcodes: int
    collection_rows: int
    matched_rows: int
    unmatched_rows: int
    unmatched_passcodes: int
    message: str
