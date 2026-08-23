"""The CSV export contract.

The authoritative definition lives in the scanner app's
``lib/data/export/collection_csv.dart``. This module mirrors it; a drift between
the two must fail loudly rather than silently produce wrong numbers.
"""

from __future__ import annotations

__all__ = [
    "COLLECTION_COLUMNS",
    "CONDITIONS",
    "CONDITION_RANK",
    "condition_rank_sql",
    "EDITIONS",
    "ISO_FORMAT",
    "NULLABLE_TEXT_COLUMNS",
    "APOSTROPHE_GUARDED_COLUMNS",
    "NATURAL_KEY",
]

#: The twelve columns, in export order. Order is part of the contract.
COLLECTION_COLUMNS: tuple[str, ...] = (
    "passcode",
    "name",
    "set_code",
    "set_name",
    "rarity",
    "condition",
    "edition",
    "language",
    "quantity",
    "notes",
    "created_at",
    "updated_at",
)

#: Cardmarket order, best to worst.
CONDITIONS: tuple[str, ...] = (
    "MINT",
    "NEAR_MINT",
    "EXCELLENT",
    "GOOD",
    "LIGHT_PLAYED",
    "PLAYED",
    "POOR",
)

#: Sort key for condition; lower is better. Used wherever grades are ordered.
CONDITION_RANK: dict[str, int] = {name: i for i, name in enumerate(CONDITIONS)}

def condition_rank_sql(column: str = "condition") -> str:
    """SQL that sorts grades best-first, from the one rank table above."""
    whens = " ".join(
        f"WHEN '{name}' THEN {rank}" for name, rank in CONDITION_RANK.items()
    )
    return f"CASE {column} {whens} ELSE {len(CONDITIONS)} END"


EDITIONS: tuple[str, ...] = ("FIRST", "UNLIMITED", "LIMITED")

#: The subsecond-less ISO-8601 shape. One of the two the loader parses, and the
#: one every CSV this app writes uses — so a timestamp written by the merge, by
#: a hand-entered row or by a revision reads back byte-identical.
ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

#: Written as '' by the exporter when absent. Normalized to NULL once, on load.
NULLABLE_TEXT_COLUMNS: tuple[str, ...] = ("set_code", "set_name", "rarity", "notes")

#: The exporter's formula-injection guard can prefix these with an apostrophe.
#: Numbers, enum codes and ISO timestamps never start with a trigger character.
APOSTROPHE_GUARDED_COLUMNS: tuple[str, ...] = ("name", "notes")

#: A row's identity — the scanner's UNIQUE key with the surrogate printing id
#: projected away. There is no row id. Rows arrive already deduplicated.
NATURAL_KEY: tuple[str, ...] = (
    "passcode",
    "set_code",
    "set_name",
    "rarity",
    "condition",
    "edition",
    "language",
)

#: Language is deliberately not an enum: the column is free-form and unlisted
#: values are valid. EN, DE, FR, IT, SP, PT, JP, KR and AE are merely the ones
#: the scanner offers.
