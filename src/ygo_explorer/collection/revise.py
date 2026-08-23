"""Changing and removing rows that are already in the collection.

An edit is not a third kind of write. It is a *removal followed by an add*: the
row as it stood is dropped, and the row as it should be is folded back in
through the same grouping every other write uses. Which gives, for free, the
behaviour the scanner app has — editing a row into a printing, grade, edition
and language you already own merges into that row rather than creating a second
one of the same thing. A delete is the same operation with nothing folded back.

Doing it this way rather than by updating a row in place is what makes a
quantity edit correct. The old row is gone before the sum happens, so setting a
row of two copies to five yields five, not seven.

Like ``merge.py``, nothing here modifies an input: the result is written to a
new CSV, because the CSV *is* the storage.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .merge import fold_to_csv, load, session
from .schema import NATURAL_KEY

__all__ = ["KEY_MATCH", "key_values", "revise_to_csv"]

#: A parameterized, NULL-safe match on the natural key, for a WHERE clause.
#: ``IS NOT DISTINCT FROM`` rather than ``=`` because three of the seven key
#: columns are nullable and ``NULL = NULL`` is NULL, not true — the same reason
#: merge.py groups rather than joins. Exported because the API needs the same
#: match to check a row exists before it writes anything.
KEY_MATCH = " AND ".join(f"{column} IS NOT DISTINCT FROM ?" for column in NATURAL_KEY)

_DECLARATION = ", ".join(f"{column} VARCHAR" for column in NATURAL_KEY)
_PLACEHOLDERS = ", ".join("?" * len(NATURAL_KEY))
_ANTI = " AND ".join(f"d.{column} IS NOT DISTINCT FROM loaded.{column}" for column in NATURAL_KEY)


def key_values(key: Mapping[str, Any]) -> list[Any]:
    """A key's seven values in ``NATURAL_KEY`` order — the order ``KEY_MATCH`` binds."""
    return [key[column] for column in NATURAL_KEY]


def revise_to_csv(
    existing: Path,
    out_path: Path,
    *,
    drop_keys: Sequence[Mapping[str, Any]],
    incoming: Path | None = None,
) -> None:
    """Write ``existing`` minus ``drop_keys``, plus ``incoming``, to ``out_path``.

    Quantities are always summed, and deliberately not configurable. On the
    delete-only path there is no incoming side for an incoming-wins rule to
    prefer, so the alternative degrades to ``max(quantity)`` — which would
    silently lose copies rather than doing anything useful.

    One side effect of folding through a ``GROUP BY``: were ``existing`` ever to
    hold two rows sharing a natural key, they come out as one row with their
    quantities added. The scanner's UNIQUE constraint forbids that and nothing
    this app writes can produce it, so it only reaches here from a hand-edited
    file — where collapsing them is a repair, not a loss, since the key is this
    app's notion of identity everywhere else too.

    Args:
        existing: the export to revise. Read only.
        out_path: the file to write. Overwritten if it exists.
        drop_keys: mappings carrying at least the ``NATURAL_KEY`` columns. Keys
            matching no row are simply not found; the caller decides whether
            that is an error.
        incoming: an export to fold in after the drop — the replacement rows of
            an edit. ``None`` for a plain delete.
    """
    with session() as con:
        load(con, "loaded", existing)

        con.execute(f"CREATE TABLE dropped ({_DECLARATION})")
        if drop_keys:
            con.executemany(
                f"INSERT INTO dropped VALUES ({_PLACEHOLDERS})",
                [key_values(key) for key in drop_keys],
            )

        con.execute(
            f"""
            CREATE TABLE kept AS
            SELECT * FROM loaded
            WHERE NOT EXISTS (SELECT 1 FROM dropped d WHERE {_ANTI})
            """
        )

        # Same shape fold_to_csv expects of a merge: src 0 for what survived,
        # 1 for what is arriving.
        stack = "SELECT 0 AS src, * FROM kept"
        if incoming is not None:
            load(con, "staged", incoming)
            stack += " UNION ALL BY NAME SELECT 1 AS src, * FROM staged"
        con.execute(f"CREATE TABLE stacked AS {stack}")

        fold_to_csv(con, "stacked", out_path, sum_quantities=True)
