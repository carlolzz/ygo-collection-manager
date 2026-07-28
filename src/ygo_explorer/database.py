"""One place that opens a fully wired connection: ledger plus catalogue."""

from __future__ import annotations

from pathlib import Path

import duckdb

from .catalogue.views import attach_catalogue
from .collection.loader import open_collection

__all__ = ["open_database"]


def open_database(
    csv_path: Path | str | None = None,
    *,
    cache_dir: Path | None = None,
) -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB holding the collection and whatever catalogue exists.

    Args:
        csv_path: the export to read; defaults to the newest one in the data dir.
        cache_dir: where the derived catalogue parquet lives; defaults to the
            configured cache. Tests point it at a temp directory.
    """
    con = open_collection(csv_path)
    if cache_dir is None:
        attach_catalogue(con)
    else:
        attach_catalogue(
            con,
            cards_path=cache_dir / "cards.parquet",
            card_sets_path=cache_dir / "card_sets.parquet",
            card_prices_path=cache_dir / "card_prices.parquet",
        )
    return con
