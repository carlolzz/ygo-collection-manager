"""Valuation. Every route here is a POST, reached by a click and nothing else.

Nothing fetches a price on page load, on scroll, on a filter change or on a
timer. A price that appears without being asked for is a bug, not a
convenience: it makes request volume a function of how the user browses.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ...config import DEFAULT_PRICE_FIELD
from ...pricing.refine import JobRegistry, RefineJob, run_refinement
from ...pricing.snapshots import SnapshotStore
from ...pricing.valuation import Valuation, value_rows
from ...pricing.ygoprodeck import CURRENCY_BY_FIELD
from ..deps import Database, get_db, get_jobs, get_store
from ..models import MoneyOut, RefineJobOut, ValuationOut, ValuedRowOut

router = APIRouter(prefix="/valuation", tags=["valuation"])


def _age_days(when: datetime | None) -> float | None:
    """How old the price data is, so the number is never mistaken for live."""
    if when is None:
        return None
    return (datetime.now(timezone.utc) - when).total_seconds() / 86400.0


def _out(valuation: Valuation) -> ValuationOut:
    return ValuationOut(
        total=MoneyOut.of(valuation.total),
        currency=valuation.currency,
        provider=valuation.provider,
        source_field=valuation.source_field,
        is_estimate=valuation.is_estimate,
        caveat=valuation.caveat,
        per_printing_rows=valuation.per_printing_rows,
        per_passcode_rows=valuation.per_passcode_rows,
        unpriced_rows=valuation.unpriced_rows,
        unpriced_copies=valuation.unpriced_copies,
        price_data_age_days=_age_days(valuation.priced_at),
        rows=[
            ValuedRowOut(
                passcode=r.passcode,
                name=r.name,
                set_code=r.set_code,
                set_name=r.set_name,
                rarity=r.rarity,
                condition=r.condition,
                edition=r.edition,
                language=r.language,
                quantity=r.quantity,
                basis=r.basis,
                unit_price=MoneyOut.of(r.unit_price),
                multiplier=str(r.multiplier),
                subtotal=MoneyOut.of(r.subtotal),
            )
            for r in valuation.rows
        ],
    )


def _validated_field(source_field: str) -> str:
    if source_field not in CURRENCY_BY_FIELD:
        raise HTTPException(
            422,
            f"Unknown price field {source_field!r}. Expected one of "
            f"{list(CURRENCY_BY_FIELD)}. A run picks one field, and therefore "
            "one currency.",
        )
    return source_field


@router.post("/collection", response_model=ValuationOut)
def value_collection(
    db: Annotated[Database, Depends(get_db)],
    store: Annotated[SnapshotStore, Depends(get_store)],
    source_field: Annotated[str, Query()] = DEFAULT_PRICE_FIELD,
) -> ValuationOut:
    """Value the whole collection.

    A local join against the cached dump: zero network requests, well under a
    second on a few thousand rows. There is deliberately no progress reporting
    here — a progress bar would be pretending.
    """
    return _out(
        value_rows(db.cursor(), store, source_field=_validated_field(source_field))
    )


@router.post("/card/{passcode}", response_model=ValuationOut)
def value_card(
    passcode: str,
    db: Annotated[Database, Depends(get_db)],
    store: Annotated[SnapshotStore, Depends(get_store)],
    source_field: Annotated[str, Query()] = DEFAULT_PRICE_FIELD,
) -> ValuationOut:
    """Value one card's rows."""
    con = db.cursor()
    if not con.execute(
        "SELECT 1 FROM collection WHERE passcode = ? LIMIT 1", [passcode]
    ).fetchone():
        raise HTTPException(404, f"Passcode {passcode} is not in the collection.")
    return _out(
        value_rows(
            con, store, source_field=_validated_field(source_field), passcode=passcode
        )
    )


# --- the per-printing refinement job -----------------------------------------


def _job_out(job: RefineJob) -> RefineJobOut:
    return RefineJobOut(
        id=job.id,
        status=job.status,
        done=job.done,
        total=job.total,
        current_set_code=job.current_set_code,
        refined=job.refined,
        unavailable=job.unavailable,
        failed=job.failed,
        skipped_fresh=job.skipped_fresh,
        errors=job.errors,
    )


@router.post("/refine", response_model=RefineJobOut, status_code=202)
async def start_refinement(
    db: Annotated[Database, Depends(get_db)],
    store: Annotated[SnapshotStore, Depends(get_store)],
    jobs: Annotated[JobRegistry, Depends(get_jobs)],
) -> RefineJobOut:
    """Fetch printing-specific prices the bulk dump lacks.

    The only per-row network work in the app. Bounded concurrency behind the
    shared token bucket, resumable, and one retry at most on a transient.
    """
    running = jobs.active()
    if running is not None:
        raise HTTPException(
            409,
            f"Refinement job {running.id} is already running "
            f"({running.done}/{running.total}). Cancel it or wait.",
        )
    job = jobs.create()
    asyncio.create_task(run_refinement(job, db.cursor(), store))
    return _job_out(job)


@router.get("/refine/{job_id}", response_model=RefineJobOut)
def refinement_progress(
    job_id: str, jobs: Annotated[JobRegistry, Depends(get_jobs)]
) -> RefineJobOut:
    """Progress as done / total, with the set code currently in flight."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"No refinement job {job_id}.")
    return _job_out(job)


@router.delete("/refine/{job_id}", response_model=RefineJobOut)
def cancel_refinement(
    job_id: str, jobs: Annotated[JobRegistry, Depends(get_jobs)]
) -> RefineJobOut:
    """Cancel mid-run. Snapshots already fetched are kept, and a re-run resumes."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"No refinement job {job_id}.")
    job.cancel()
    return _job_out(job)
