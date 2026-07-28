"""The shared database handle."""

from __future__ import annotations

from pathlib import Path

import duckdb
from fastapi import Request

from ..database import open_database

__all__ = ["Database", "get_db"]


class Database:
    """Holds the loaded collection for the app's lifetime.

    The export is read once at startup, so a rename of a column fails the app
    loudly on boot rather than on some later request. ``cursor()`` hands each
    request its own handle over the same in-memory database, since FastAPI runs
    sync endpoints on a thread pool.
    """

    def __init__(self, csv_path: Path | str | None = None) -> None:
        self._con = open_database(csv_path)

    def cursor(self) -> duckdb.DuckDBPyConnection:
        return self._con.cursor()

    def reload(self, csv_path: Path | str | None = None) -> None:
        """Re-read the export and re-attach the catalogue, e.g. after a refresh."""
        self._con.close()
        self._con = open_database(csv_path)

    def close(self) -> None:
        self._con.close()


def get_db(request: Request) -> Database:
    return request.app.state.db
