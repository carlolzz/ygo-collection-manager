"""The per-printing refinement job.

This is the only per-row network work in the app. ``cardsetsinfo.php?setcode=X``
returns a printing-specific ``set_price``, which is strictly better than the
per-passcode number where a set code is known and the bulk dump has no price for
that printing.

Everything about the job is shaped by the API rules: a shared token bucket well
under 20 req/s, bounded concurrency, progress reported, cancellable mid-run,
resumable, and **no retry storm** — one retry, on a genuine transient, then the
failure is recorded and the run moves past it.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import duckdb
import httpx

from ..config import CARDSETSINFO_URL, PRICE_STALENESS_DAYS
from ..net.limiter import shared_limiter
from .snapshots import STATUS_ERROR, STATUS_OK, STATUS_UNAVAILABLE, SnapshotStore

__all__ = ["RefineJob", "JobRegistry", "REFINE_PROVIDER", "REFINE_SOURCE_FIELD"]

REFINE_PROVIDER = "ygoprodeck"
REFINE_SOURCE_FIELD = "set_price"  # USD, per the API guide

CONCURRENCY = 4  # bounded; the limiter is the real ceiling
RETRY_DELAY_SECONDS = 2.0
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

# Owned printings the bulk dump could not price. Anything the dump already
# prices needs no request at all — the refinement is the exception, not the path.
_CANDIDATES = """
SELECT DISTINCT c.passcode, c.set_code
FROM collection_enriched c
LEFT JOIN card_sets s
       ON s.card_id = c.card_id AND s.set_code = c.set_code
WHERE c.set_code IS NOT NULL
  AND (s.set_price_usd IS NULL)
ORDER BY c.set_code
"""


@dataclass
class RefineJob:
    """A run's observable state. Polled by the UI as ``done / total``."""

    id: str
    total: int = 0
    done: int = 0
    refined: int = 0
    unavailable: int = 0
    failed: int = 0
    skipped_fresh: int = 0
    current_set_code: str | None = None
    status: str = "pending"  # pending | running | cancelled | finished | error
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    errors: list[str] = field(default_factory=list)
    _cancel: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def cancel(self) -> None:
        """Stop after the in-flight requests. Fetched snapshots stay put."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()


class JobRegistry:
    """The running and recently finished jobs, by id."""

    def __init__(self) -> None:
        self._jobs: dict[str, RefineJob] = {}

    def create(self) -> RefineJob:
        job = RefineJob(id=uuid.uuid4().hex[:12])
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> RefineJob | None:
        return self._jobs.get(job_id)

    def active(self) -> RefineJob | None:
        return next((j for j in self._jobs.values() if j.status == "running"), None)


def _parse_price(payload: object) -> Decimal | None:
    """cardsetsinfo.php returns set_price as a string, and "0.00" for no data."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get("set_price")
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value > 0 else None


async def _fetch_one(
    client: httpx.AsyncClient, set_code: str
) -> tuple[Decimal | None, str | None]:
    """One set code, at most one retry. Returns (price, error)."""
    for attempt in (1, 2):
        await shared_limiter().acquire()
        try:
            response = await client.get(CARDSETSINFO_URL, params={"setcode": set_code})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == 1:
                # A genuine transient, once, after a fixed delay. Never a loop.
                await asyncio.sleep(RETRY_DELAY_SECONDS)
                continue
            return None, f"{type(exc).__name__}: {exc}"

        if response.status_code >= 500 and attempt == 1:
            await asyncio.sleep(RETRY_DELAY_SECONDS)
            continue
        if response.status_code != 200:
            return None, f"HTTP {response.status_code}"

        try:
            return _parse_price(response.json()), None
        except ValueError as exc:
            return None, f"unparseable response: {exc}"

    return None, "exhausted the single permitted retry"


async def run_refinement(
    job: RefineJob,
    con: duckdb.DuckDBPyConnection,
    store: SnapshotStore,
    *,
    client: httpx.AsyncClient | None = None,
    max_age_days: int = PRICE_STALENESS_DAYS,
) -> RefineJob:
    """Fetch printing prices the dump lacks, recording every outcome."""
    candidates = [(r[0], r[1]) for r in con.execute(_CANDIDATES).fetchall()]

    # Resumability: a key with a fresh snapshot is skipped, including one that
    # previously failed — so an interrupted run costs only what it had not done,
    # and a set code the source cannot price is not asked about forever.
    fresh = store.fresh_keys(REFINE_PROVIDER, REFINE_SOURCE_FIELD, max_age_days)
    pending = [k for k in candidates if k not in fresh]

    job.total = len(pending)
    job.skipped_fresh = len(candidates) - len(pending)
    job.status = "running"

    if not pending:
        job.status = "finished"
        job.finished_at = datetime.now(timezone.utc)
        return job

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
    semaphore = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()

    async def worker(key: tuple[str, str]) -> None:
        passcode, set_code = key
        if job.cancelled:
            return
        async with semaphore:
            if job.cancelled:
                return
            price, error = await _fetch_one(client, set_code)

        async with lock:
            if error is not None:
                status, detail = STATUS_ERROR, error
                job.failed += 1
                if len(job.errors) < 20:
                    job.errors.append(f"{set_code}: {error}")
            elif price is None:
                status, detail = STATUS_UNAVAILABLE, "no set_price for this printing"
                job.unavailable += 1
            else:
                status, detail = STATUS_OK, "cardsetsinfo"
                job.refined += 1

            store.record(
                key,
                provider=REFINE_PROVIDER,
                currency="USD",  # set_price is USD on every path
                source_field=REFINE_SOURCE_FIELD,
                amount=price,
                status=status,
                detail=detail,
            )
            job.done += 1
            job.current_set_code = set_code

    try:
        await asyncio.gather(*(worker(k) for k in pending))
    finally:
        if owns_client:
            await client.aclose()
        store.flush()

    job.status = "cancelled" if job.cancelled else "finished"
    job.finished_at = datetime.now(timezone.utc)
    return job
