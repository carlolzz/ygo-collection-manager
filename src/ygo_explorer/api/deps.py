"""The shared database handle and the price snapshot store."""

from __future__ import annotations

from pathlib import Path

import duckdb
from fastapi import Request

from ..catalogue.views import attach_catalogue
from ..collection.loader import open_collection
from ..config import collection_csv_path
from ..pricing.refine import JobRegistry
from ..pricing.snapshots import SnapshotStore

__all__ = ["Database", "get_db", "get_store", "get_jobs"]

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
            self._con.execute(_EMPTY_COLLECTION)
            self.csv_path = None
            self.has_collection = False

        attach_catalogue(self._con)

    def cursor(self) -> duckdb.DuckDBPyConnection:
        return self._con.cursor()

    def reload(self, csv_path: Path | str | None = None) -> None:
        """Re-read the export and re-attach the catalogue, e.g. after a refresh."""
        if csv_path is not None:
            self._requested = csv_path
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
