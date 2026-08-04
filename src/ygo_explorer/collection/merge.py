"""Combining an uploaded export with the one already loaded.

Two exports overlap whenever they describe the same *printing in the same
state* — the ``NATURAL_KEY``. What should happen to the quantities when they do
is not something this module can decide: an export of everything scanned since
last time wants the copies added, while a fresh full export of the whole
collection wants them replaced. So both are offered and the caller chooses.

The result is written out as a new CSV rather than kept in memory, because the
CSV *is* the storage — the app rebuilds its tables from whichever export in the
data directory sorts last. Neither input file is modified.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from .loader import guard_expr, normalized_query, register_fold, validate_header
from .schema import COLLECTION_COLUMNS, NATURAL_KEY

__all__ = ["MergeCounts", "merge_counts", "merge_to_csv"]


class MergeCounts:
    """How the two exports overlap, in the terms the upload dialog asks about."""

    __slots__ = ("incoming_rows", "overlapping_rows", "new_rows")

    def __init__(self, incoming_rows: int, overlapping_rows: int, new_rows: int) -> None:
        self.incoming_rows = incoming_rows
        self.overlapping_rows = overlapping_rows
        self.new_rows = new_rows


#: Grouping rather than joining. A GROUP BY treats two NULLs as the same group,
#: which is exactly what is wanted for the nullable key columns — set_code,
#: set_name and rarity are all absent on a hand-entered row, and two such rows
#: for the same card are the same row. An equijoin would drop them instead.
_KEY = ", ".join(NATURAL_KEY)


@contextmanager
def _stacked(existing: Path, incoming: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    """Both exports, normalized and stacked into one ``stacked`` table.

    ``src`` says which side a row came from: 0 loaded, 1 uploaded. Materialized
    rather than left as CTEs, because the normalization is itself a ``WITH``
    query and cannot simply be nested inside another one.
    """
    validate_header(incoming)
    with duckdb.connect() as con:
        con.execute("SET TimeZone = 'UTC'")
        # The normalization computes fold(name), so the UDF must exist even
        # though nothing here reads the folded column.
        register_fold(con)
        con.execute(f"CREATE TABLE loaded AS {normalized_query(existing)}")
        con.execute(f"CREATE TABLE uploaded AS {normalized_query(incoming)}")
        con.execute(
            "CREATE TABLE stacked AS "
            "SELECT 0 AS src, * FROM loaded "
            "UNION ALL BY NAME "
            "SELECT 1 AS src, * FROM uploaded"
        )
        yield con


def merge_counts(existing: Path, incoming: Path) -> MergeCounts:
    """Count how much of ``incoming`` the loaded collection already has.

    Both sides are read through the loader's normalization, so the key is built
    from the same trimmed, unguarded values the app itself compares.
    """
    with _stacked(existing, incoming) as con:
        rows, overlapping, new = con.execute(
            f"""
            SELECT
                (SELECT COUNT(*) FROM uploaded),
                COUNT(*) FILTER (WHERE in_loaded AND in_uploaded),
                COUNT(*) FILTER (WHERE in_uploaded AND NOT in_loaded)
            FROM (
                SELECT bool_or(src = 0) AS in_loaded, bool_or(src = 1) AS in_uploaded
                FROM stacked GROUP BY {_KEY}
            )
            """
        ).fetchone()
    return MergeCounts(int(rows), int(overlapping), int(new))


def _quantity(sum_quantities: bool) -> str:
    if sum_quantities:
        return "SUM(quantity)::INTEGER"
    # The upload is the more recent statement of what is owned, so it wins —
    # including when it says fewer, which is how selling two copies is recorded.
    # The outer max() is the fallback for a row only the old export has.
    return "COALESCE(max(quantity) FILTER (WHERE src = 1), max(quantity))::INTEGER"


def _newest(column: str) -> str:
    """Prefer the incoming export's value for a column outside the key."""
    return f"COALESCE(any_value({column}) FILTER (WHERE src = 1), any_value({column}))"


# The two ISO-8601 shapes the loader accepts; this is the one without
# subseconds, so a written timestamp reads back through try_strptime unchanged.
_ISO = "'%Y-%m-%dT%H:%M:%SZ'"


def merge_to_csv(
    existing: Path, incoming: Path, out_path: Path, *, sum_quantities: bool
) -> None:
    """Write the two exports combined to ``out_path``, in the export contract.

    Columns are projected in ``COLLECTION_COLUMNS`` order and the apostrophe
    guard is re-applied, so the output is an export like any other and the
    loader reads it back with no special case.
    """
    # Keyed by column so the contract order below is the single place that
    # decides the output shape — a column added to the export contract and not
    # to this table fails loudly here rather than writing a silently wrong CSV.
    exprs = {
        **{key: key for key in NATURAL_KEY},
        "name": guard_expr(_newest("name")),
        "notes": guard_expr(_newest("notes")),
        "quantity": _quantity(sum_quantities),
        # Owned since the earlier of the two, last touched at the later.
        "created_at": f"strftime(min(created_at) AT TIME ZONE 'UTC', {_ISO})",
        "updated_at": f"strftime(max(updated_at) AT TIME ZONE 'UTC', {_ISO})",
    }
    projection = ",\n                ".join(
        f"{exprs[column]} AS {column}" for column in COLLECTION_COLUMNS
    )

    destination = str(out_path.resolve().as_posix()).replace("'", "''")
    with _stacked(existing, incoming) as con:
        con.execute(
            f"""
            COPY (
                SELECT {projection}
                FROM stacked
                GROUP BY {_KEY}
                ORDER BY name, set_code, condition, edition, language
            ) TO '{destination}'
            (FORMAT CSV, HEADER, DELIMITER ',', QUOTE '"', ESCAPE '"')
            """
        )
