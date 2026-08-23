"""The catalogue refresh, as a job the UI can watch.

The download is two files and some forty megabytes, and before this it was one
blocking POST that said nothing until it was done. A user with a slow line had
no way to tell a working download from a hung one, so this reports what has
landed and how long the rest is likely to take.

The estimate is measured, never assumed: bytes per second observed on this
connection, smoothed, against the sizes the server declares. The one part that
cannot be measured — deriving the parquet, which reports no progress of its own
— says so rather than inventing a number for it.

Shaped after ``pricing.refine``: same registry, same poll-a-job-by-id endpoint,
same one-at-a-time rule.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import monotonic
from typing import TYPE_CHECKING

from .dump import DumpProgress, fetch_dump

if TYPE_CHECKING:  # the API depends on the catalogue, never the other way round
    from ..api.deps import Database

__all__ = ["RefreshJob", "RefreshRegistry", "run_refresh"]

#: What to assume a step weighs before it has started and said otherwise. Only
#: reached if the server sends no Content-Length on the first download either;
#: the real numbers are ~21 MB for the English dump and ~19 MB per language.
NOMINAL_STEP_BYTES = 20_000_000

#: The share of the bar the downloads own. The rest belongs to the parquet
#: derivation, which has no progress to report — so the bar stops here and the
#: phase label carries the news, rather than sitting at 100% while work goes on.
DOWNLOAD_SHARE = 85.0

#: Weight of the newest rate observation. Low, because the first seconds of a
#: transfer are always unrepresentative and a jumping countdown is worse than a
#: slightly stale one.
_RATE_ALPHA = 0.25

log = logging.getLogger(__name__)


@dataclass
class RefreshJob:
    """A refresh's observable state. Polled by the UI while it runs."""

    id: str
    status: str = "pending"  # pending | running | finished | error
    phase: str = "starting"  # starting | cards | names | building
    #: The language whose names are being fetched, during ``names``.
    language: str | None = None
    downloaded_bytes: int = 0
    expected_bytes: int | None = None
    percent: float = 0.0
    #: None whenever there is nothing honest to say — before the first bytes,
    #: and throughout the unmeasurable build phase.
    eta_seconds: float | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    #: Why it failed. The endpoint returns long before the work does, so this is
    #: the only route a failure has to the screen.
    error: str | None = None

    # Per step, so a step that restarts or reports out of order cannot double
    # count. The totals are always derived from these, never accumulated.
    _done: dict[int, int] = field(default_factory=dict, repr=False)
    _expected: dict[int, int | None] = field(default_factory=dict, repr=False)
    _rate: float | None = field(default=None, repr=False)  # bytes/sec, smoothed
    _last_at: float = field(default_factory=monotonic, repr=False)
    _last_bytes: int = field(default=0, repr=False)

    def record(self, progress: DumpProgress) -> None:
        """Fold one report from ``fetch_dump`` into the numbers on show."""
        self.phase = progress.phase
        self.language = progress.language

        if progress.phase == "building":
            # Nothing measurable left to say: the bar holds where the downloads
            # left it and the phase speaks for itself.
            self.eta_seconds = None
            self.percent = DOWNLOAD_SHARE
            return

        self._done[progress.step] = progress.downloaded
        self._expected[progress.step] = progress.expected

        self.downloaded_bytes = sum(self._done.values())
        self.expected_bytes = self._estimate_total(progress.steps)
        self._update_rate()

        if self.expected_bytes:
            fraction = min(1.0, self.downloaded_bytes / self.expected_bytes)
            self.percent = fraction * DOWNLOAD_SHARE
            remaining = max(0, self.expected_bytes - self.downloaded_bytes)
            self.eta_seconds = remaining / self._rate if self._rate else None

    def _estimate_total(self, steps: int) -> int:
        """What the whole download weighs, counting steps not yet begun.

        A step the server has declared a size for contributes that size. One
        that has not started yet contributes the nominal — the first declared
        size we saw, since the dumps are within a few megabytes of each other,
        and a constant only if the server declared nothing at all.
        """
        declared = [size for size in self._expected.values() if size]
        nominal = declared[0] if declared else NOMINAL_STEP_BYTES
        total = sum(self._expected.get(step) or nominal for step in range(1, steps + 1))
        # Never less than what has already arrived. A server that declares a
        # compressed length against a body we measure decoded would otherwise
        # drive the bar past its own end.
        return max(total, self.downloaded_bytes)

    def _update_rate(self) -> None:
        now = monotonic()
        elapsed = now - self._last_at
        # Below a quarter second the sample is mostly measurement noise, and
        # dividing by it produces a rate no connection ever had.
        if elapsed < 0.25:
            return
        sample = (self.downloaded_bytes - self._last_bytes) / elapsed
        self._last_at, self._last_bytes = now, self.downloaded_bytes
        if sample <= 0:
            return
        self._rate = (
            sample
            if self._rate is None
            else self._rate * (1 - _RATE_ALPHA) + sample * _RATE_ALPHA
        )

    def _finish(self, status: str, error: str | None = None) -> None:
        self.status = status
        self.error = error
        self.eta_seconds = None
        self.finished_at = datetime.now(timezone.utc)
        if status == "finished":
            self.percent = 100.0


class RefreshRegistry:
    """The running and recently finished refreshes, by id."""

    def __init__(self) -> None:
        self._jobs: dict[str, RefreshJob] = {}
        self._tasks: set[asyncio.Task] = set()

    def create(self) -> RefreshJob:
        job = RefreshJob(id=uuid.uuid4().hex[:12])
        self._jobs[job.id] = job
        return job

    def start(self, coro) -> None:
        """Run the work detached, holding the task while it runs.

        Held because asyncio keeps only a weak reference of its own: a task
        nobody names can be collected mid-download.
        """
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def get(self, job_id: str) -> RefreshJob | None:
        return self._jobs.get(job_id)

    def active(self) -> RefreshJob | None:
        return next((j for j in self._jobs.values() if j.status == "running"), None)


async def run_refresh(job: RefreshJob, db: "Database", *, force: bool) -> None:
    """Download the dumps and reopen the database on the freshly written parquet.

    Runs detached from the request that started it, so nothing here may raise:
    a failure has to land on the job or it reaches no one.
    """
    job.status = "running"
    try:
        await fetch_dump(force=force, on_progress=job.record)
        # The same reopen the blocking endpoint used to do, and for the same
        # reason: without it every later query reads the parquet we replaced.
        db.reload()
    except asyncio.CancelledError:
        job._finish("error", "The refresh was cancelled before it finished.")
        raise
    except Exception as exc:
        log.warning("catalogue refresh %s failed", job.id, exc_info=True)
        job._finish("error", f"{type(exc).__name__}: {exc}")
    else:
        job._finish("finished")
