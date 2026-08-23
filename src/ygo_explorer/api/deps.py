"""The shared database handle and the price snapshot store."""

from __future__ import annotations

from pathlib import Path

import duckdb
from fastapi import Request

from ..catalogue.views import attach_catalogue
from ..collection.loader import open_collection, register_fold
from ..config import collection_csv_path
from ..pricing.refine import JobRegistry
from ..pricing.snapshots import SnapshotStore

__all__ = ["Database", "get_db", "get_store", "get_jobs"]

#: Distinguishes "re-open what you had" from an explicit "go back to whichever
#: export in the data directory is newest", which None now means.
_KEEP: object = object()

# The empty collection, so every query still parses and returns zero rows rather
# than the app refusing to start. Matches what open_collection produces.
_EMPTY_COLLECTION = """
CREATE OR REPLACE TABLE collection (
    passcode VARCHAR, passcode_key VARCHAR, name VARCHAR, name_folded VARCHAR,
    set_code VARCHAR, set_name VARCHAR, rarity VARCHAR, condition VARCHAR,
    edition VARCHAR, language VARCHAR, quantity INTEGER, quantity_raw VARCHAR,
    notes VARCHAR, created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    created_at_raw VARCHAR, updated_at_raw VARCHAR
)
"""


class Database:
    """Holds the loaded collection for the app's lifetime.

    The export is read once at startup, so a renamed column fails on boot with
    the column named rather than on some later request. But a *missing* export
    is not an error: the container ships with an empty mount and the user has
    yet to add their CSV, so the app comes up with an empty collection and says
    so. ``cursor()`` hands each request its own handle, since FastAPI runs sync
    endpoints on a thread pool.
    """

    def __init__(self, csv_path: Path | str | None = None) -> None:
        self._requested = csv_path
        self._open()

    def _open(self) -> None:
        try:
            path = (
                Path(self._requested)
                if self._requested is not None
                else collection_csv_path()
            )
            exists = path.is_file()
        except FileNotFoundError:
            path, exists = None, False

        if exists:
            self._con = open_collection(path)
            self.csv_path: Path | None = path
            self.has_collection = True
        else:
            self._con = duckdb.connect()
            self._con.execute("SET TimeZone = 'UTC'")
            # Registered here too, not only in open_collection: the card picker
            # queries the catalogue before there is any collection to load, and
            # a first-run user searching for their first card must not hit a
            # missing fold().
            register_fold(self._con)
            self._con.execute(_EMPTY_COLLECTION)
            self.csv_path = None
            self.has_collection = False

        attach_catalogue(self._con)

    def cursor(self) -> duckdb.DuckDBPyConnection:
        return self._con.cursor()

    @property
    def requested(self) -> Path | str | None:
        """The explicitly requested export, if any — what ``reload()`` re-opens.

        Read before an upload so a failed one can put the handle back exactly
        as it was, rather than leaving the app on an empty collection.
        """
        return self._requested

    def reload(self, csv_path: Path | str | None | object = _KEEP) -> None:
        """Re-read the export and re-attach the catalogue, e.g. after a refresh.

        The default re-opens whatever was requested before. Passing ``None``
        explicitly means the opposite: go back to picking the newest export in
        the data directory, which is how an upload is rolled back.
        """
        if csv_path is not _KEEP:
            self._requested = csv_path  # type: ignore[assignment]
        self._con.close()
        self._open()

    @property
    def message(self) -> str:
        if self.has_collection:
            return f"Loaded {self.csv_path.name}."
        return (
            "No collection export found. Add a CSV exported from the scanner app "
            "to the data directory, or upload one, to get started."
        )

    def close(self) -> None:
        self._con.close()


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_store(request: Request) -> SnapshotStore:
    return request.app.state.snapshots


def get_jobs(request: Request) -> JobRegistry:
    return request.app.state.jobs
