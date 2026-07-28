"""Flatten the bulk dump into three parquet tables the query layer can join.

Splitting cards, printings and prices apart keeps each one at its natural grain:
one row per passcode, one per printing, one per card. Prices are carried as text
and cast to DECIMAL downstream, so no amount ever passes through a float.

Written with DuckDB rather than a dataframe library: it is already the query
engine, it writes parquet natively, and the alternative added ~360 MB to the
published image to do a job DuckDB does in one statement.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from ..config import CARD_PRICES_PARQUET, CARD_SETS_PARQUET, CARDS_PARQUET
from ..text import fold

__all__ = [
    "normalize_dump",
    "cards_rows",
    "card_sets_rows",
    "card_prices_rows",
    "passcode_key",
    "CARDS_SCHEMA",
    "CARD_SETS_SCHEMA",
    "CARD_PRICES_SCHEMA",
]

# The five price fields and the currency each is quoted in. YGOPRODeck mixes
# currencies inside one response, so the currency is baked into the column name:
# there is then no way to sum two of them without writing the mistake out in full.
PRICE_FIELDS: tuple[tuple[str, str], ...] = (
    ("cardmarket_price", "cardmarket_price_eur"),
    ("tcgplayer_price", "tcgplayer_price_usd"),
    ("ebay_price", "ebay_price_usd"),
    ("amazon_price", "amazon_price_usd"),
    ("coolstuffinc_price", "coolstuffinc_price_usd"),
)

CARDS_SCHEMA: dict[str, str] = {
    "passcode": "VARCHAR",
    "passcode_key": "VARCHAR",
    "card_id": "VARCHAR",
    "is_alternate_art": "BOOLEAN",
    "name": "VARCHAR",
    "name_folded": "VARCHAR",
    "type": "VARCHAR",
    "frame_type": "VARCHAR",
    "attribute": "VARCHAR",
    "race": "VARCHAR",
    "archetype": "VARCHAR",
    "atk": "INTEGER",
    "defense": "INTEGER",
    "level": "INTEGER",
    "description": "VARCHAR",
    "image_url": "VARCHAR",
    "image_url_small": "VARCHAR",
    "image_url_cropped": "VARCHAR",
}

CARD_SETS_SCHEMA: dict[str, str] = {
    "card_id": "VARCHAR",
    "set_code": "VARCHAR",
    "set_name": "VARCHAR",
    "set_rarity": "VARCHAR",
    "set_rarity_code": "VARCHAR",
    "set_price_usd": "VARCHAR",
}

CARD_PRICES_SCHEMA: dict[str, str] = {"card_id": "VARCHAR"} | {
    column: "VARCHAR" for _, column in PRICE_FIELDS
}


def passcode_key(passcode: str | int) -> str:
    """The canonical join form: leading zeros ignored, still a string.

    Must agree with the SQL expression in ``collection.loader``.
    """
    text = str(passcode).strip()
    stripped = text.lstrip("0")
    return stripped if stripped else "0"


def _price(value: object) -> str | None:
    """Normalize a price field to text, or None.

    YGOPRODeck writes "0.00" when it has no price rather than omitting the field.
    Kept as None so an absent price is never mistaken for a card genuinely worth
    nothing, and so it shows up in the "couldn't be priced" count.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if float(text) == 0.0:
            return None
    except ValueError:
        return None
    return text


def _int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def cards_rows(cards: list[dict]) -> list[dict]:
    """One row per passcode, including alternate-artwork passcodes.

    A card's alt arts are listed under ``card_images[].id`` and are *not*
    top-level ``id``s — Dark Magician is 46986414, but its Starter Deck: Yugi
    printing reports 46986421. Indexing only the top-level id silently fails to
    match those rows, so every image id gets an entry pointing back at the same
    card.
    """
    rows: list[dict] = []
    seen: set[str] = set()

    for card in cards:
        card_id = str(card["id"])
        images = card.get("card_images") or []
        # The top-level id first, so it wins if an image repeats it.
        candidates: list[tuple[str, dict]] = [(card_id, images[0] if images else {})]
        candidates += [(str(img["id"]), img) for img in images if "id" in img]

        for passcode, image in candidates:
            if passcode in seen:
                continue
            seen.add(passcode)
            name = card.get("name") or ""
            rows.append(
                {
                    "passcode": passcode,
                    "passcode_key": passcode_key(passcode),
                    "card_id": card_id,
                    "is_alternate_art": passcode != card_id,
                    "name": name,
                    "name_folded": fold(name),
                    "type": card.get("type"),
                    "frame_type": card.get("frameType"),
                    "attribute": card.get("attribute"),
                    "race": card.get("race"),
                    "archetype": card.get("archetype"),
                    "atk": _int(card.get("atk")),
                    "defense": _int(card.get("def")),
                    "level": _int(card.get("level")),
                    "description": card.get("desc"),
                    "image_url": image.get("image_url"),
                    "image_url_small": image.get("image_url_small"),
                    "image_url_cropped": image.get("image_url_cropped"),
                }
            )
    return rows


def card_sets_rows(cards: list[dict]) -> list[dict]:
    """One row per printing.

    ``set_price`` is already here, which is why per-printing valuation is a local
    join rather than a request per set code. It is quoted in USD, as is
    cardsetsinfo.php — there is no EUR equivalent at printing grain.
    """
    return [
        {
            "card_id": str(card["id"]),
            "set_code": entry.get("set_code"),
            "set_name": entry.get("set_name"),
            "set_rarity": entry.get("set_rarity"),
            "set_rarity_code": entry.get("set_rarity_code"),
            "set_price_usd": _price(entry.get("set_price")),
        }
        for card in cards
        for entry in (card.get("card_sets") or [])
    ]


def card_prices_rows(cards: list[dict]) -> list[dict]:
    """One row per card: the per-passcode prices, one column per currency."""
    rows: list[dict] = []
    for card in cards:
        prices = (card.get("card_prices") or [{}])[0]
        row = {"card_id": str(card["id"])}
        row.update({column: _price(prices.get(field)) for field, column in PRICE_FIELDS})
        rows.append(row)
    return rows


def _write_parquet(path: Path, schema: dict[str, str], rows: list[dict]) -> int:
    """Write typed rows to parquet. An empty table still gets its columns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(schema)
    ddl = ", ".join(f"{name} {sql_type}" for name, sql_type in schema.items())

    with duckdb.connect() as con:
        con.execute(f"CREATE TABLE t ({ddl})")
        if rows:
            placeholders = ", ".join("?" * len(columns))
            con.executemany(
                f"INSERT INTO t VALUES ({placeholders})",
                [[row.get(c) for c in columns] for row in rows],
            )
        literal = str(path.resolve().as_posix()).replace("'", "''")
        con.execute(f"COPY t TO '{literal}' (FORMAT PARQUET)")
    return len(rows)


def normalize_dump(
    cards: list[dict],
    *,
    cards_path: Path = CARDS_PARQUET,
    card_sets_path: Path = CARD_SETS_PARQUET,
    card_prices_path: Path = CARD_PRICES_PARQUET,
) -> dict[str, int]:
    """Write the three tables; return each one's row count."""
    written = {
        cards_path: _write_parquet(cards_path, CARDS_SCHEMA, cards_rows(cards)),
        card_sets_path: _write_parquet(
            card_sets_path, CARD_SETS_SCHEMA, card_sets_rows(cards)
        ),
        card_prices_path: _write_parquet(
            card_prices_path, CARD_PRICES_SCHEMA, card_prices_rows(cards)
        ),
    }
    return {path.stem: count for path, count in written.items()}
