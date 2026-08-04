"""Load the collection export into DuckDB, validating the schema on the way in.

The CSV is opened read-only and is never written to. Every normalization the
rest of the app relies on — empty string to NULL, the apostrophe guard, the
timestamp parse, the canonical join key — happens exactly once, here.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from ..config import collection_csv_path
from ..text import fold
from .schema import COLLECTION_COLUMNS, CONDITIONS, EDITIONS

__all__ = [
    "CollectionError",
    "CollectionSchemaError",
    "CollectionDataError",
    "open_collection",
    "read_header",
    "row_count",
    "normalized_query",
    "guard_expr",
    "register_fold",
    "validate_header",
]


class CollectionError(Exception):
    """Base for anything wrong with the collection export."""


class CollectionSchemaError(CollectionError):
    """The CSV's columns do not match the export contract."""


class CollectionDataError(CollectionError):
    """The CSV's columns are right but a value in them is not."""


# Every field is read as text so that leading zeros survive and every cast is
# explicit below. The dialect is stated rather than sniffed.
_READ_CSV = (
    "read_csv({path}, header = true, all_varchar = true, "
    "delim = ',', quote = '\"', escape = '\"')"
)


def _read_csv_expr(csv_path: Path) -> str:
    literal = str(csv_path.resolve().as_posix()).replace("'", "''")
    return _READ_CSV.format(path=f"'{literal}'")


def read_header(csv_path: Path) -> tuple[str, ...]:
    """Return the CSV's column names, in file order."""
    with duckdb.connect() as con:
        rows = con.execute(
            f"DESCRIBE SELECT * FROM {_read_csv_expr(csv_path)}"
        ).fetchall()
    return tuple(row[0] for row in rows)


def row_count(csv_path: Path) -> int:
    """How many rows an export holds, header excluded."""
    with duckdb.connect() as con:
        return int(
            con.execute(f"SELECT COUNT(*) FROM {_read_csv_expr(csv_path)}").fetchone()[0]
        )


def validate_header(csv_path: Path) -> None:
    """Fail loudly, naming the column, before a single number is computed."""
    actual = read_header(csv_path)
    if actual == COLLECTION_COLUMNS:
        return

    expected_set, actual_set = set(COLLECTION_COLUMNS), set(actual)
    missing = [c for c in COLLECTION_COLUMNS if c not in actual_set]
    unexpected = [c for c in actual if c not in expected_set]

    problems: list[str] = []
    if missing and unexpected:
        problems.append(
            f"renamed or replaced column(s): missing {missing}, found {unexpected} instead"
        )
    else:
        if missing:
            problems.append(f"missing column(s): {missing}")
        if unexpected:
            problems.append(f"unexpected column(s): {unexpected}")
    if not problems:
        problems.append(
            f"columns are out of contract order: expected {list(COLLECTION_COLUMNS)}, "
            f"got {list(actual)}"
        )

    raise CollectionSchemaError(
        f"{csv_path} does not match the collection export contract — "
        + "; ".join(problems)
    )


def register_fold(con: duckdb.DuckDBPyConnection) -> None:
    """Expose the one diacritic-folding function to SQL as ``fold()``."""

    def _fold(value: str | None) -> str | None:
        return None if value is None else fold(value)

    con.create_function("fold", _fold, ["VARCHAR"], "VARCHAR")


# Strips at most one leading apostrophe — the exporter adds exactly one, so a
# value that legitimately begins with two keeps the second.
def _unguard(column: str) -> str:
    return (
        f"CASE WHEN starts_with({column}, '''') "
        f"THEN substr({column}, 2) ELSE {column} END"
    )


#: What the exporter's guard exists to defuse: the characters a spreadsheet
#: treats as the start of a formula. Tab and carriage return are spelled with
#: chr() so the generated SQL stays readable and has no invisible characters.
_FORMULA_TRIGGERS = ("'='", "'+'", "'-'", "'@'", "chr(9)", "chr(13)")


def guard_expr(column: str) -> str:
    """The inverse of ``_unguard``: re-apply the exporter's injection guard.

    Only needed when this app *writes* a CSV — the merge does. Without it a
    merged export would hand a spreadsheet a card named ``-Ancient Gear`` as a
    formula, which is the very thing the scanner's guard prevents.
    """
    triggers = ", ".join(_FORMULA_TRIGGERS)
    return (
        f"CASE WHEN {column} IS NOT NULL AND left({column}, 1) IN ({triggers}) "
        f"THEN '''' || {column} ELSE {column} END"
    )


# The two ISO-8601 shapes Dart's toIso8601String can emit for a UTC instant.
_TIMESTAMP_FORMATS = "['%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ']"


def _utc(column: str) -> str:
    return f"try_strptime({column}, {_TIMESTAMP_FORMATS}) AT TIME ZONE 'UTC'"


_NORMALIZE = f"""
WITH raw AS (SELECT * FROM {{source}}),
unguarded AS (
    SELECT
        trim(passcode)                                  AS passcode,
        {_unguard("name")}                              AS name,
        nullif(trim(set_code), '')                      AS set_code,
        nullif(trim(set_name), '')                      AS set_name,
        nullif(trim(rarity), '')                        AS rarity,
        condition,
        edition,
        language,
        quantity                                        AS quantity_raw,
        {_unguard("nullif(notes, '')")}                 AS notes,
        created_at                                      AS created_at_raw,
        updated_at                                      AS updated_at_raw
    FROM raw
)
SELECT
    passcode,
    -- Canonical form for joining to the catalogue only. YGOPRODeck ids are
    -- integers, and the export's passcodes vary in width (the real export
    -- contains a seven-digit one), so leading zeros must not decide a match.
    -- The displayed passcode is always the untouched string above.
    CASE WHEN ltrim(passcode, '0') = '' THEN '0' ELSE ltrim(passcode, '0') END
                                                        AS passcode_key,
    name,
    fold(name)                                          AS name_folded,
    set_code,
    set_name,
    rarity,
    condition,
    edition,
    language,
    TRY_CAST(quantity_raw AS INTEGER)                   AS quantity,
    quantity_raw,
    notes,
    {_utc("created_at_raw")}                            AS created_at,
    {_utc("updated_at_raw")}                            AS updated_at,
    created_at_raw,
    updated_at_raw
FROM unguarded
"""

_BUILD_COLLECTION = "CREATE OR REPLACE TABLE collection AS " + _NORMALIZE


def normalized_query(csv_path: Path) -> str:
    """The normalizing SELECT over one export, as a subquery-ready string.

    Exposed so a *second* CSV can be read through the identical normalization —
    the merge compares rows by the natural key, and a key built from raw text
    would not match one built from trimmed, unguarded text.
    """
    return _NORMALIZE.format(source=_read_csv_expr(csv_path))


def _validate_data(con: duckdb.DuckDBPyConnection, csv_path: Path) -> None:
    bad_quantity = con.execute(
        "SELECT passcode, quantity_raw FROM collection "
        "WHERE quantity IS NULL OR quantity < 1 LIMIT 5"
    ).fetchall()
    if bad_quantity:
        raise CollectionDataError(
            f"{csv_path}: 'quantity' must be an integer >= 1; offending rows "
            f"(passcode, value): {bad_quantity}"
        )

    bad_timestamps = con.execute(
        "SELECT passcode, created_at_raw, updated_at_raw FROM collection "
        "WHERE created_at IS NULL OR updated_at IS NULL LIMIT 5"
    ).fetchall()
    if bad_timestamps:
        raise CollectionDataError(
            f"{csv_path}: 'created_at'/'updated_at' must be UTC ISO-8601; offending "
            f"rows (passcode, created_at, updated_at): {bad_timestamps}"
        )

    for column, allowed in (("condition", CONDITIONS), ("edition", EDITIONS)):
        unknown = con.execute(
            f"SELECT DISTINCT {column} FROM collection "
            f"WHERE {column} NOT IN ({', '.join('?' * len(allowed))})",
            list(allowed),
        ).fetchall()
        if unknown:
            raise CollectionDataError(
                f"{csv_path}: unknown '{column}' value(s) "
                f"{[u[0] for u in unknown]}; expected one of {list(allowed)}"
            )
    # 'language' is intentionally unvalidated: the column is free-form.


def open_collection(
    csv_path: Path | str | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> duckdb.DuckDBPyConnection:
    """Validate the export and materialize it as the ``collection`` table.

    Materialized rather than left as a view over ``read_csv`` so the normalization
    and the ``fold`` UDF run once, not on every query. The CSV itself is only ever
    read.

    Raises:
        CollectionSchemaError: a column is missing, renamed, extra or misordered.
        CollectionDataError: a column is present but holds a value it may not.
    """
    path = Path(csv_path) if csv_path is not None else collection_csv_path()
    if not path.is_file():
        raise FileNotFoundError(f"No collection export at {path}")

    validate_header(path)

    con = con if con is not None else duckdb.connect()
    # Without this the session renders TIMESTAMPTZ in the machine's local zone,
    # so the same export would read differently in Rome and in Tokyo.
    con.execute("SET TimeZone = 'UTC'")
    register_fold(con)
    con.execute(_BUILD_COLLECTION.format(source=_read_csv_expr(path)))
    _validate_data(con, path)
    return con
