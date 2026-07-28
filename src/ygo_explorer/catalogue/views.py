"""Join the ownership ledger to the card catalogue.

The join is a LEFT JOIN in one direction only, and deliberately so: the CSV is
the source of truth for what is owned, and a card the dump has never heard of
must still appear with its name, quantity and condition intact.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from ..config import CARD_PRICES_PARQUET, CARD_SETS_PARQUET, CARDS_PARQUET

__all__ = ["attach_catalogue", "CATALOGUE_TABLES"]

# The catalogue schema lives here, once, so the tables exist with the right
# shape whether or not a dump has ever been downloaded. Money is DECIMAL, never
# float, and every price column names its own currency.
CATALOGUE_TABLES: dict[str, str] = {
    "cards": """
        passcode           VARCHAR,
        passcode_key       VARCHAR,
        card_id            VARCHAR,
        is_alternate_art   BOOLEAN,
        name               VARCHAR,
        name_folded        VARCHAR,
        type               VARCHAR,
        frame_type         VARCHAR,
        attribute          VARCHAR,
        race               VARCHAR,
        archetype          VARCHAR,
        atk                INTEGER,
        defense            INTEGER,
        level              INTEGER,
        description        VARCHAR,
        image_url          VARCHAR,
        image_url_small    VARCHAR,
        image_url_cropped  VARCHAR
    """,
    "card_sets": """
        card_id            VARCHAR,
        set_code           VARCHAR,
        set_name           VARCHAR,
        set_rarity         VARCHAR,
        set_rarity_code    VARCHAR,
        set_price_usd      DECIMAL(12, 2)
    """,
    "card_prices": """
        card_id                 VARCHAR,
        cardmarket_price_eur    DECIMAL(12, 2),
        tcgplayer_price_usd     DECIMAL(12, 2),
        ebay_price_usd          DECIMAL(12, 2),
        amazon_price_usd        DECIMAL(12, 2),
        coolstuffinc_price_usd  DECIMAL(12, 2)
    """,
}


def _columns(ddl: str) -> list[str]:
    return [line.split()[0] for line in ddl.strip().splitlines()]


def _load_parquet(
    con: duckdb.DuckDBPyConnection, table: str, path: Path
) -> None:
    """Fill a catalogue table from parquet, casting text prices to DECIMAL.

    Prices are written as text upstream precisely so this cast is the only place
    they acquire a numeric type — and it is a decimal one.
    """
    columns = _columns(CATALOGUE_TABLES[table])
    projection = ", ".join(f"CAST({c} AS {_type(table, c)}) AS {c}" for c in columns)
    literal = str(path.resolve().as_posix()).replace("'", "''")
    con.execute(
        f"INSERT INTO {table} SELECT {projection} FROM read_parquet('{literal}')"
    )


def _type(table: str, column: str) -> str:
    for line in CATALOGUE_TABLES[table].strip().splitlines():
        parts = line.strip().rstrip(",").split(None, 1)
        if parts[0] == column:
            return parts[1]
    raise KeyError(f"{table}.{column}")


_ENRICHED = """
CREATE OR REPLACE VIEW collection_enriched AS
SELECT
    c.*,
    k.card_id,
    k.passcode        AS catalogue_passcode,
    k.is_alternate_art,
    k.name            AS catalogue_name,
    k.type,
    k.frame_type,
    k.attribute,
    k.race,
    k.archetype,
    k.atk,
    k.defense,
    k.level,
    k.description,
    k.image_url,
    k.image_url_small,
    k.image_url_cropped,
    -- False means the dump has no entry for this passcode. The row still shows;
    -- its card attributes are simply unknown.
    (k.passcode_key IS NOT NULL) AS in_catalogue
FROM collection c
LEFT JOIN cards k USING (passcode_key)
"""

# Ownership rolled up to one row per card, which is the grain the grid renders.
_BY_CARD = """
CREATE OR REPLACE VIEW collection_by_card AS
SELECT
    passcode,
    passcode_key,
    any_value(card_id)             AS card_id,
    any_value(name)                AS name,
    any_value(name_folded)         AS name_folded,
    any_value(type)                AS type,
    any_value(frame_type)          AS frame_type,
    any_value(attribute)           AS attribute,
    any_value(race)                AS race,
    any_value(archetype)           AS archetype,
    any_value(atk)                 AS atk,
    any_value(defense)             AS defense,
    any_value(level)               AS level,
    any_value(image_url_small)     AS image_url_small,
    bool_or(in_catalogue)          AS in_catalogue,
    SUM(quantity)::BIGINT          AS total_copies,
    COUNT(*)::BIGINT               AS row_count,
    COUNT(DISTINCT set_code)       AS printing_count,
    min(created_at)                AS first_acquired_at,
    max(updated_at)                AS last_updated_at
FROM collection_enriched
GROUP BY passcode, passcode_key
"""

_STATUS = """
CREATE OR REPLACE VIEW catalogue_status AS
SELECT
    (SELECT COUNT(*) FROM cards)                                 AS catalogue_passcodes,
    (SELECT COUNT(DISTINCT card_id) FROM cards)                  AS catalogue_cards,
    (SELECT COUNT(*) FROM collection)                            AS collection_rows,
    (SELECT COUNT(*) FROM collection_enriched WHERE in_catalogue) AS matched_rows,
    (SELECT COUNT(*) FROM collection_enriched WHERE NOT in_catalogue)
                                                                 AS unmatched_rows,
    (SELECT COUNT(DISTINCT passcode) FROM collection_enriched WHERE NOT in_catalogue)
                                                                 AS unmatched_passcodes
"""


def attach_catalogue(
    con: duckdb.DuckDBPyConnection,
    *,
    cards_path: Path = CARDS_PARQUET,
    card_sets_path: Path = CARD_SETS_PARQUET,
    card_prices_path: Path = CARD_PRICES_PARQUET,
) -> None:
    """Create the catalogue tables and the joined views on an open connection.

    Safe to call before any dump has been fetched: the tables are created empty,
    every collection row reports ``in_catalogue = false``, and the app works with
    card attributes shown as unknown.
    """
    paths = {
        "cards": cards_path,
        "card_sets": card_sets_path,
        "card_prices": card_prices_path,
    }
    for table, ddl in CATALOGUE_TABLES.items():
        con.execute(f"CREATE OR REPLACE TABLE {table} ({ddl})")
        if paths[table].is_file():
            _load_parquet(con, table, paths[table])

    con.execute(_ENRICHED)
    con.execute(_BY_CARD)
    con.execute(_STATUS)
