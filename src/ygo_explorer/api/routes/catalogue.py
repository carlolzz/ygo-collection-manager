"""Catalogue provenance, and the one endpoint allowed to touch the network."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ...catalogue.dump import fetch_dump, load_meta
from ..deps import Database, get_db
from ..models import CatalogueStatus

router = APIRouter(prefix="/catalogue", tags=["catalogue"])


def _status(db: Database) -> CatalogueStatus:
    row = db.cursor().execute(
        "SELECT catalogue_passcodes, catalogue_cards, collection_rows, matched_rows, "
        "unmatched_rows, unmatched_passcodes FROM catalogue_status"
    ).fetchone()
    meta = load_meta()

    if meta is None:
        message = "No card dump cached. Card attributes and prices are unavailable."
    elif row[4]:
        message = (
            f"Priced from a dump fetched {meta.age_days:.1f} days ago. "
            f"{row[5]} owned passcode(s) are not in it and show no card attributes."
        )
    else:
        message = f"Dump fetched {meta.age_days:.1f} days ago; every owned card matched."

    return CatalogueStatus(
        fetched_at=meta.fetched_at_utc if meta else None,
        age_days=meta.age_days if meta else None,
        catalogue_passcodes=row[0],
        catalogue_cards=row[1],
        collection_rows=row[2],
        matched_rows=row[3],
        unmatched_rows=row[4],
        unmatched_passcodes=row[5],
        message=message,
    )


@router.get("/status", response_model=CatalogueStatus)
def catalogue_status(db: Annotated[Database, Depends(get_db)]) -> CatalogueStatus:
    """How old the card data is, and how much of the collection it covers."""
    return _status(db)


@router.post("/refresh", response_model=CatalogueStatus)
async def refresh_catalogue(
    db: Annotated[Database, Depends(get_db)],
    force: Annotated[bool, Query(description="Refetch even if a cache exists")] = False,
) -> CatalogueStatus:
    """Download the bulk dump. The only network call in the read API.

    A POST, and only ever reached by a click: nothing here runs on page load, on
    scroll, on a filter change or on a timer.
    """
    await fetch_dump(force=force)
    # Re-open so the freshly written parquet is what the next query reads.
    db.reload()
    return _status(db)
