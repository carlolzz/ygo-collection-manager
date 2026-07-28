"""The append-only price snapshot store.

Two load-bearing reasons it exists: it caches aggressively against a
rate-limited API, and it records history so "collection value over time" is
possible later without re-deriving a past nobody wrote down.

Therefore rows are **never updated in place** — that history is the point. A
refetch appends; the current price is the newest row for a key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import duckdb

from ..config import CACHE_DIR, PRICE_STALENESS_DAYS
from ..money import Money
from .provider import PriceKey

__all__ = ["Snapshot", "SnapshotStore", "STATUS_OK", "STATUS_UNAVAILABLE", "STATUS_ERROR"]

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"  # asked, and the source has no price
STATUS_ERROR = "error"  # asked, and the request failed

_SCHEMA = """
    passcode      VARCHAR NOT NULL,
    set_code      VARCHAR,
    provider      VARCHAR NOT NULL,
    currency      VARCHAR NOT NULL,
    source_field  VARCHAR NOT NULL,
    amount        DECIMAL(12, 2),
    fetched_at    TIMESTAMP WITH TIME ZONE NOT NULL,
    status        VARCHAR NOT NULL,
    detail        VARCHAR
"""

_COLUMNS = (
    "passcode", "set_code", "provider", "currency", "source_field",
    "amount", "fetched_at", "status", "detail",
)


@dataclass(frozen=True)
class Snapshot:
    passcode: str
    set_code: str | None
    provider: str
    currency: str
    source_field: str
    amount: Decimal | None
    fetched_at: datetime
    status: str
    detail: str | None = None

    @property
    def money(self) -> Money | None:
        if self.amount is None or self.status != STATUS_OK:
            return None
        return Money(self.amount, self.currency)

    def is_fresh(self, max_age_days: int = PRICE_STALENESS_DAYS) -> bool:
        return self.age_days <= max_age_days

    @property
    def age_days(self) -> float:
        return (datetime.now(timezone.utc) - self.fetched_at).total_seconds() / 86400.0


class SnapshotStore:
    """Snapshots in DuckDB, persisted to parquet.

    Held open for the app's lifetime. ``flush`` writes the parquet; callers that
    append should flush before the process exits.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else CACHE_DIR / "price_snapshots.parquet"
        self._con = duckdb.connect()
        self._con.execute("SET TimeZone = 'UTC'")
        self._con.execute(f"CREATE TABLE snapshots ({_SCHEMA})")
        if self.path.is_file():
            literal = str(self.path.resolve().as_posix()).replace("'", "''")
            self._con.execute(
                f"INSERT INTO snapshots SELECT {', '.join(_COLUMNS)} "
                f"FROM read_parquet('{literal}')"
            )

    # --- writing -------------------------------------------------------------

    def record(
        self,
        key: PriceKey,
        *,
        provider: str,
        currency: str,
        source_field: str,
        amount: Decimal | None,
        status: str,
        detail: str | None = None,
        fetched_at: datetime | None = None,
    ) -> None:
        """Append one observation. Failures are recorded too.

        A recorded failure is what lets a resumed run tell "not tried" from
        "tried and unavailable", so it never re-asks for something the source
        has already said it does not have.
        """
        passcode, set_code = key
        self._con.execute(
            f"INSERT INTO snapshots ({', '.join(_COLUMNS)}) VALUES (?,?,?,?,?,?,?,?,?)",
            [
                passcode,
                set_code,
                provider,
                currency,
                source_field,
                amount,
                fetched_at or datetime.now(timezone.utc),
                status,
                detail,
            ],
        )

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        literal = str(self.path.resolve().as_posix()).replace("'", "''")
        self._con.execute(f"COPY snapshots TO '{literal}' (FORMAT PARQUET)")

    # --- reading -------------------------------------------------------------

    _LATEST = f"""
        SELECT {', '.join(_COLUMNS)} FROM (
            SELECT *, row_number() OVER (
                PARTITION BY passcode, set_code, provider, source_field
                ORDER BY fetched_at DESC
            ) AS recency
            FROM snapshots
            WHERE provider = ? AND source_field = ?
        ) WHERE recency = 1
    """

    def latest(self, provider: str, source_field: str) -> dict[PriceKey, Snapshot]:
        """The newest snapshot per key. Older rows stay put; this only reads."""
        rows = self._con.execute(self._LATEST, [provider, source_field]).fetchall()
        out: dict[PriceKey, Snapshot] = {}
        for row in rows:
            snap = Snapshot(**dict(zip(_COLUMNS, row)))
            out[(snap.passcode, snap.set_code)] = snap
        return out

    def fresh_keys(
        self,
        provider: str,
        source_field: str,
        max_age_days: int = PRICE_STALENESS_DAYS,
    ) -> set[PriceKey]:
        """Keys with a snapshot new enough to reuse, whatever its status.

        Includes failures on purpose: a set code the source has already said it
        cannot price should not be asked again on the next resume.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        return {
            key
            for key, snap in self.latest(provider, source_field).items()
            if snap.fetched_at >= cutoff
        }

    def newest_fetched_at(self, provider: str, source_field: str) -> datetime | None:
        row = self._con.execute(
            "SELECT max(fetched_at) FROM snapshots WHERE provider = ? AND source_field = ?",
            [provider, source_field],
        ).fetchone()
        return row[0] if row else None

    def count(self) -> int:
        return self._con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]

    def close(self) -> None:
        self._con.close()
