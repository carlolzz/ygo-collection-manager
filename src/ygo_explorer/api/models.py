"""Response shapes.

Count fields are named for exactly which count they are. There is no field
called ``count``: the difference between "how many copies" and "how many
distinct cards" is the single easiest thing to get wrong here, so no label is
allowed to be ambiguous about it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from ..collection.schema import CONDITIONS, EDITIONS

__all__ = [
    "CardSummary",
    "CardPage",
    "OwnedRow",
    "CataloguePrinting",
    "CatalogueCard",
    "NewEntry",
    "NewEntries",
    "EntryKey",
    "EntryKeys",
    "EntryEdit",
    "CardDetail",
    "Bucket",
    "TimeBucket",
    "Stats",
    "FilterOptions",
    "CatalogueStatus",
    "CollectionStatus",
    "UploadPreview",
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
    languages: list[str] = Field(
        default_factory=list,
        description=(
            "Every distinct language owned, sorted. Free-form in the export, so "
            "this is not an enum and may hold codes the scanner does not offer."
        ),
    )


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


class CatalogueCard(BaseModel):
    """A card the cached dump knows, owned or not. What the card picker offers."""

    passcode: str
    name: str
    type: str | None = None
    printing_count: int = Field(
        description="Distinct printings the dump lists, i.e. how many the picker offers."
    )
    owned_copies: int = Field(
        description="Copies already in the collection. Zero is the common case here."
    )
    matched_name: str | None = Field(
        default=None,
        description=(
            "The name that matched, when it was not the English one above — so a "
            "localized search can show what it found. Never written to the "
            "collection: a row's name is always the English one."
        ),
    )
    matched_language: str | None = Field(
        default=None, description="Language of matched_name, when there is one."
    )


class NewEntry(BaseModel):
    """One row asked for by hand, before anything is written.

    The same twelve columns the scanner exports, minus the two timestamps, which
    are the server's to stamp. Every copy carries its own printing, grade,
    edition and language, so three copies of one card in three languages are
    three of these — that is the whole reason the request takes a list.
    """

    passcode: str = Field(
        pattern=r"^[0-9]{1,8}$",
        description="1-8 digits, kept as a string: leading zeros are part of it.",
    )
    name: str = Field(min_length=1)
    set_code: str | None = None
    set_name: str | None = None
    rarity: str | None = None
    condition: str = Field(description=f"One of {list(CONDITIONS)}.")
    edition: str = Field(description=f"One of {list(EDITIONS)}.")
    language: str = Field(
        min_length=1,
        description=(
            "Free-form by contract, so an unlisted code is accepted and only "
            "upper-cased. EN, DE, FR, IT, SP, PT, JP, KR and AE are what the "
            "scanner offers."
        ),
    )
    quantity: int = Field(ge=1, description="Copies this row stands for.")
    notes: str | None = None

    @field_validator("passcode", "name", "language", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    # Absent is '' on the wire and NULL in the file. Normalizing here means the
    # natural key of a hand-entered row matches an imported one with no set.
    @field_validator("set_code", "set_name", "rarity", "notes", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("language")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @field_validator("condition")
    @classmethod
    def _known_condition(cls, value: str) -> str:
        if value not in CONDITIONS:
            raise ValueError(f"unknown condition {value!r}; expected one of {list(CONDITIONS)}")
        return value

    @field_validator("edition")
    @classmethod
    def _known_edition(cls, value: str) -> str:
        if value not in EDITIONS:
            raise ValueError(f"unknown edition {value!r}; expected one of {list(EDITIONS)}")
        return value


class NewEntries(BaseModel):
    """A save: one card's copies, or several cards' — the server does not care."""

    rows: list[NewEntry] = Field(
        min_length=1,
        max_length=500,
        description="Rows identical in printing, grade, edition and language are folded into one.",
    )


class EntryKey(BaseModel):
    """Which row, out of everything owned — the seven ``NATURAL_KEY`` columns.

    Deliberately *not* validated the way ``NewEntry`` is, despite the overlap.
    This is a lookup of a value already on file, not a value being written: the
    loader leaves ``condition``, ``edition`` and ``language`` exactly as the CSV
    spells them, so a row stored as ``" en "`` is served back verbatim by the
    card endpoint. Trimming or upper-casing here — or enforcing the passcode
    pattern — would make a row that plainly exists impossible to address, which
    is a worse failure than accepting a key that matches nothing.

    There is no row id to use instead: the export contract has none, and adding
    one would mean this app's CSVs no longer being the scanner's CSVs.
    """

    passcode: str
    set_code: str | None = None
    set_name: str | None = None
    rarity: str | None = None
    condition: str
    edition: str
    language: str

    # The one normalization that is safe, and necessary: the browser sends '' for
    # a column the loader stored as NULL.
    @field_validator("set_code", "set_name", "rarity", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class EntryKeys(BaseModel):
    """Rows to remove. Every key must match, or none of them are removed."""

    keys: list[EntryKey] = Field(min_length=1, max_length=500)


class EntryEdit(BaseModel):
    """A row as it stands, and the row it should become.

    The replacement is an ordinary ``NewEntry`` — an edit writes the same ten
    columns a hand-entered row does, and there is no reason for it to be
    validated any more loosely.
    """

    key: EntryKey
    row: NewEntry


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
    race: list[str] = Field(
        description="The raw upstream column, which mixes all three taxonomies below."
    )
    monster_type: list[str] = Field(description="Monster races only.")
    spell_type: list[str] = Field(description="Spell subtypes only.")
    trap_type: list[str] = Field(description="Trap subtypes only.")
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


class CatalogueJobOut(BaseModel):
    """Progress of a card-data download."""

    id: str
    status: str = Field(description="pending | running | finished | error")
    phase: str = Field(description="starting | cards | names | building")
    language: str | None = Field(
        default=None, description="The language being fetched, during 'names'."
    )
    downloaded_bytes: int
    expected_bytes: int | None = None
    percent: float
    eta_seconds: float | None = Field(
        default=None,
        description="Measured from this connection's throughput. Null when there "
        "is nothing honest to say — before the first bytes, and while the "
        "catalogue is being built.",
    )
    error: str | None = Field(
        default=None,
        description="Set when status is 'error'. The only route a failure has to "
        "the UI, since the endpoint returns before the work does.",
    )


class DeckCardOut(BaseModel):
    passcode: str
    name: str
    needed: int = Field(description="Copies the list calls for, across all zones.")
    owned: int = Field(description="Copies owned, any printing, condition or language.")
    missing: int
    zones: dict[str, int]
    unit_price: MoneyOut | None = None
    subtotal: MoneyOut | None = None
    held_elsewhere: int = Field(
        default=0,
        description="Of the copies owned, how many other flagged deck checks "
        "are holding. They do not count towards this deck.",
    )
    held_by: list[str] = Field(
        default_factory=list, description="The names of the checks holding them."
    )


class DeckCheckOut(BaseModel):
    """A saved deck check, with its counts as of now."""

    id: str
    name: str
    source_format: str
    created_at: datetime
    checked_at: datetime
    owned: bool = Field(
        description="Whether the check holds the copies it uses, so other "
        "checks do not count them."
    )
    flagged_at: datetime | None = Field(
        default=None,
        description="When the flag went on. An earlier flag wins a contested copy.",
    )
    total_needed: int
    total_missing: int
    copies_held: int = Field(description="Copies this check is holding right now.")


class DeckCheckPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    owned: bool | None = None


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
    missing_ydke: str = Field(
        default="",
        description="The missing copies as a ydke:// code. Empty if nothing is missing.",
    )
    missing_text: str = Field(
        default="",
        description="The missing copies as a zone-grouped plaintext list.",
    )
    cards: list[DeckCardOut]
    check: DeckCheckOut | None = Field(
        default=None, description="The saved check this analysis belongs to."
    )
    text: str = Field(default="", description="The list as it was pasted.")


class CollectionStatus(BaseModel):
    """Whether an export is loaded at all — the app runs without one."""

    has_collection: bool
    csv_path: str | None = None
    collection_rows: int = 0
    message: str


class UploadPreview(BaseModel):
    """What an export would do to the loaded collection, before it does it.

    Rows are counted by the natural key — printing, condition, edition and
    language — so "already there" means the same card in the same state, not
    merely the same card.
    """

    has_collection: bool = Field(
        description="False when nothing is loaded; the upload then simply loads this file."
    )
    current_rows: int = 0
    incoming_rows: int = Field(default=0, description="Rows in the uploaded file.")
    overlapping_rows: int = Field(
        default=0, description="Uploaded rows the collection already has."
    )
    new_rows: int = Field(default=0, description="Uploaded rows the collection does not have.")


class CatalogueStatus(BaseModel):
    fetched_at: datetime | None = None
    age_days: float | None = None
    languages: list[str] = Field(
        default_factory=list,
        description=(
            "Languages whose name index is actually cached, besides English. "
            "Empty means only English names are on disk."
        ),
    )
    search_languages: list[str] = Field(
        default_factory=list,
        description=(
            "Languages the picker offers to search in, English first. A language "
            "listed here but absent from `languages` is configured but not "
            "downloaded: offer it as unavailable rather than let it be selected "
            "and silently match nothing."
        ),
    )
    catalogue_cards: int
    catalogue_passcodes: int
    collection_rows: int
    matched_rows: int
    unmatched_rows: int
    unmatched_passcodes: int
    message: str
