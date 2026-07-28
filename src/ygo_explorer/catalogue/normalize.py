"""Flatten the bulk dump into three parquet tables the query layer can join.

Splitting cards, printings and prices apart keeps each one at its natural grain:
one row per passcode, one per printing, one per card. Prices are carried as text
and cast to DECIMAL downstream, so no amount ever passes through a float.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ..config import CARD_PRICES_PARQUET, CARD_SETS_PARQUET, CARDS_PARQUET
from ..text import fold

__all__ = [
    "normalize_dump",
    "cards_frame",
    "card_sets_frame",
    "card_prices_frame",
    "passcode_key",
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


def cards_frame(cards: list[dict]) -> pl.DataFrame:
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
                    "atk": card.get("atk"),
                    "defense": card.get("def"),
                    "level": card.get("level"),
                    "description": card.get("desc"),
                    "image_url": image.get("image_url"),
                    "image_url_small": image.get("image_url_small"),
                    "image_url_cropped": image.get("image_url_cropped"),
                }
            )

    schema = {
        "passcode": pl.Utf8,
        "passcode_key": pl.Utf8,
        "card_id": pl.Utf8,
        "is_alternate_art": pl.Boolean,
        "name": pl.Utf8,
        "name_folded": pl.Utf8,
        "type": pl.Utf8,
        "frame_type": pl.Utf8,
        "attribute": pl.Utf8,
        "race": pl.Utf8,
        "archetype": pl.Utf8,
        "atk": pl.Int32,
        "defense": pl.Int32,
        "level": pl.Int32,
        "description": pl.Utf8,
        "image_url": pl.Utf8,
        "image_url_small": pl.Utf8,
        "image_url_cropped": pl.Utf8,
    }
    return pl.DataFrame(rows, schema=schema, orient="row" if rows else None)


def card_sets_frame(cards: list[dict]) -> pl.DataFrame:
    """One row per printing.

    ``set_price`` is already here, which is why per-printing valuation is a local
    join rather than a request per set code. It is quoted in USD, as is
    cardsetsinfo.php — there is no EUR equivalent at printing grain.
    """
    rows: list[dict] = []
    for card in cards:
        card_id = str(card["id"])
        for entry in card.get("card_sets") or []:
            rows.append(
                {
                    "card_id": card_id,
                    "set_code": entry.get("set_code"),
                    "set_name": entry.get("set_name"),
                    "set_rarity": entry.get("set_rarity"),
                    "set_rarity_code": entry.get("set_rarity_code"),
                    "set_price_usd": _price(entry.get("set_price")),
                }
            )
    schema = {
        "card_id": pl.Utf8,
        "set_code": pl.Utf8,
        "set_name": pl.Utf8,
        "set_rarity": pl.Utf8,
        "set_rarity_code": pl.Utf8,
        "set_price_usd": pl.Utf8,
    }
    return pl.DataFrame(rows, schema=schema, orient="row" if rows else None)


def card_prices_frame(cards: list[dict]) -> pl.DataFrame:
    """One row per card: the per-passcode prices, one column per currency."""
    rows: list[dict] = []
    for card in cards:
        prices = (card.get("card_prices") or [{}])[0]
        row = {"card_id": str(card["id"])}
        row.update(
            {column: _price(prices.get(field)) for field, column in PRICE_FIELDS}
        )
        rows.append(row)
    schema = {"card_id": pl.Utf8} | {column: pl.Utf8 for _, column in PRICE_FIELDS}
    return pl.DataFrame(rows, schema=schema, orient="row" if rows else None)


def normalize_dump(
    cards: list[dict],
    *,
    cards_path: Path = CARDS_PARQUET,
    card_sets_path: Path = CARD_SETS_PARQUET,
    card_prices_path: Path = CARD_PRICES_PARQUET,
) -> dict[str, int]:
    """Write the three tables; return each one's row count."""
    cards_path.parent.mkdir(parents=True, exist_ok=True)
    frames = {
        cards_path: cards_frame(cards),
        card_sets_path: card_sets_frame(cards),
        card_prices_path: card_prices_frame(cards),
    }
    for path, frame in frames.items():
        frame.write_parquet(path)
    return {path.stem: frame.height for path, frame in frames.items()}
