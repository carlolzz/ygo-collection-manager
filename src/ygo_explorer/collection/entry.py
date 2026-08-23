"""Rows entered by hand, staged as an export.

Adding a card is a **merge**. The rows are written here to a throwaway CSV in
the same twelve-column contract the scanner exports, and ``merge.merge_to_csv``
then folds that file into the loaded collection. Nothing in this module knows
how to combine two rows: grouping on the natural key, summing quantities and
keeping the earlier ``created_at`` already exist, once, over there.

Two consequences worth naming, both of which fall out of that reuse rather than
being decided here:

- Entering a card you already own in exactly the same printing, condition,
  edition and language does not create a second row; it increments the one you
  have. That is the scanner's ``addOrIncrement`` reached by a different road.
- Three copies described identically collapse to one row of quantity three,
  while three described differently stay three rows of one. Which is the whole
  point of letting a copy carry its own set, language and grade.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .loader import guard_text
from .schema import APOSTROPHE_GUARDED_COLUMNS, COLLECTION_COLUMNS, ISO_FORMAT

__all__ = ["ISO_FORMAT", "write_staged"]


def _cell(row: Mapping[str, Any], column: str, stamp: str) -> str:
    if column == "updated_at":
        # Always now: this row is being written, whatever else is true of it.
        return stamp
    if column == "created_at":
        # A hand-entered row is acquired at the moment it is saved, so it carries
        # no created_at and gets the same stamp. A row being *revised* carries the
        # one it already had, so correcting a condition does not rewrite when the
        # card was owned since. (A merge onto an existing row keeps the earlier of
        # the two anyway, because merge.py takes min(created_at).)
        return str(row.get(column) or stamp)
    value = row.get(column)
    if value is None:
        return ""  # the contract writes '' for absent, never a NULL token
    text = str(value)
    return (guard_text(text) or "") if column in APOSTROPHE_GUARDED_COLUMNS else text


def write_staged(
    rows: Sequence[Mapping[str, Any]],
    path: Path,
    *,
    now: datetime | None = None,
) -> None:
    """Write ``rows`` to ``path`` as an export the loader will accept.

    Values are taken by column name, so the caller hands over anything mapping-
    like — in practice the API's validated models. Columns absent from a row are
    written empty, which is only legal for the four nullable ones; the loader
    rejects the rest on the way back in, and that rejection rolls the whole save
    back. Validation is not duplicated here.

    Args:
        rows: one mapping per row, keyed by ``COLLECTION_COLUMNS`` names. A row
            may carry a ``created_at`` — a revision of a row already owned does,
            so it keeps the day it was acquired; a new row does not.
        path: the file to write. Overwritten if it exists.
        now: the timestamp for ``updated_at``, and for any row with no
            ``created_at`` of its own. Injected for tests.
    """
    if not rows:
        raise ValueError("Nothing to write: give write_staged at least one row.")

    stamp = (now or datetime.now(timezone.utc)).strftime(ISO_FORMAT)

    # newline='' is required of csv.writer, which emits its own terminator; the
    # explicit '\n' keeps the file identical on Windows and everywhere else.
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=",", quotechar='"', lineterminator="\n")
        writer.writerow(COLLECTION_COLUMNS)
        for row in rows:
            writer.writerow([_cell(row, column, stamp) for column in COLLECTION_COLUMNS])
