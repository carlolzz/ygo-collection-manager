"""Deck import: what a list needs, what is owned, and what the gap costs.

Every check is saved, and a saved check can hold the copies it uses — see
``deck.history`` and ``deck.reserve``.
"""

from __future__ import annotations

from typing import Annotated

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ...config import DEFAULT_PRICE_FIELD
from ...deck.compare import DeckAnalysis, analyze_deck, demand_of, owned_counts
from ...deck.export import missing_text, missing_ydke
from ...deck.history import DeckCheck, DeckCheckStore, DemandLine
from ...deck.parse import ParseError, parse_deck
from ...deck.reserve import held_elsewhere, totals
from ...deck.resolve import Resolution, resolve_deck
from ...pricing.ygoprodeck import CURRENCY_BY_FIELD
from ..deps import Database, get_db, get_deck_checks
from ..models import (
    DeckAnalysisOut,
    DeckCardOut,
    DeckCheckOut,
    DeckCheckPatch,
    MoneyOut,
)

router = APIRouter(prefix="/deck", tags=["deck"])

Db = Annotated[Database, Depends(get_db)]
Checks = Annotated[DeckCheckStore, Depends(get_deck_checks)]


class DeckRequest(BaseModel):
    text: str = Field(
        description="A ydke:// code, a .ydk file's contents, or a plaintext "
        "decklist. The format is detected, not declared.",
        min_length=1,
    )
    source_field: str = DEFAULT_PRICE_FIELD


def _demand_lines(resolution: Resolution) -> list[DemandLine]:
    return [
        DemandLine(card_id, info["passcode"], info["name"], info["needed"])
        for card_id, info in demand_of(resolution).items()
    ]


def _check_out(
    check: DeckCheck, con: duckdb.DuckDBPyConnection, store: DeckCheckStore
) -> DeckCheckOut:
    return _checks_out([check], con, store)[0]


def _checks_out(
    checks: list[DeckCheck], con: duckdb.DuckDBPyConnection, store: DeckCheckStore
) -> list[DeckCheckOut]:
    ownership = owned_counts(con)
    flagged = store.flagged()
    out = []
    for check in checks:
        t = totals(check, ownership, flagged)
        out.append(
            DeckCheckOut(
                id=check.id,
                name=check.name,
                source_format=check.source_format,
                created_at=check.created_at,
                checked_at=check.checked_at,
                owned=check.owned,
                flagged_at=check.flagged_at,
                total_needed=t.total_needed,
                total_missing=t.total_missing,
                copies_held=t.copies_held,
            )
        )
    return out


def _analysis_out(
    analysis: DeckAnalysis, check: DeckCheckOut | None, text: str
) -> DeckAnalysisOut:
    return DeckAnalysisOut(
        source_format=analysis.source_format,
        currency=analysis.currency,
        zone_counts=analysis.zone_counts,
        total_needed=analysis.total_needed,
        total_owned=analysis.total_owned,
        total_missing=analysis.total_missing,
        distinct_missing=analysis.distinct_missing,
        unpriced_missing_cards=analysis.unpriced_missing_cards,
        estimated_cost=MoneyOut.of(analysis.estimated_cost),
        caveat=analysis.caveat,
        unresolved=analysis.unresolved,
        missing_ydke=missing_ydke(analysis.cards),
        missing_text=missing_text(analysis.cards),
        cards=[
            DeckCardOut(
                passcode=c.passcode,
                name=c.name,
                needed=c.needed,
                owned=c.owned,
                missing=c.missing,
                zones=c.zones,
                unit_price=MoneyOut.of(c.unit_price),
                subtotal=MoneyOut.of(c.subtotal),
                held_elsewhere=c.held_elsewhere,
                held_by=list(c.held_by),
            )
            for c in analysis.cards
        ],
        check=check,
        text=text,
    )


def _run(
    con: duckdb.DuckDBPyConnection,
    store: DeckCheckStore,
    text: str,
    source_field: str,
    existing: DeckCheck | None,
) -> DeckAnalysisOut:
    """Parse, save, work out what is held elsewhere, then compare.

    Saving comes before the comparison so the held copies are worked out from
    the demand just resolved, not whatever was stored last time. Both ways a
    request can be rejected are checked first, so a rejected one saves nothing.
    """
    if source_field not in CURRENCY_BY_FIELD:
        raise HTTPException(
            422,
            f"Unknown price field {source_field!r}. Expected one of "
            f"{list(CURRENCY_BY_FIELD)}.",
        )
    try:
        deck = parse_deck(text)
    except ParseError as exc:
        raise HTTPException(422, str(exc)) from None

    resolution = resolve_deck(con, deck)
    lines = _demand_lines(resolution)
    if existing is None:
        check = store.record(text, deck.source_format, lines)
    else:
        check = store.refresh_demand(existing.id, lines) or existing

    ownership = owned_counts(con)
    held = held_elsewhere(ownership, store.flagged(), check.id)
    analysis = analyze_deck(
        con,
        deck,
        source_field=source_field,
        resolution=resolution,
        held=held,
        ownership=ownership,
    )
    return _analysis_out(analysis, _check_out(check, con, store), check.text)


@router.post("/analyze", response_model=DeckAnalysisOut)
def analyze(body: DeckRequest, db: Db, store: Checks) -> DeckAnalysisOut:
    """Compare a deck list against the collection, and save the check.

    Local only — the prices come from the cached dump, so this touches no
    network however long the list is. Checking a list already saved updates
    that check rather than adding another.
    """
    return _run(db.cursor(), store, body.text, body.source_field, existing=None)


@router.get("/checks", response_model=list[DeckCheckOut])
def list_checks(db: Db, store: Checks) -> list[DeckCheckOut]:
    """Every saved check, most recently checked first, with live counts."""
    return _checks_out(store.list(), db.cursor(), store)


def _get(store: DeckCheckStore, check_id: str) -> DeckCheck:
    check = store.get(check_id)
    if check is None:
        raise HTTPException(404, "No saved deck check with that id.")
    return check


@router.get("/checks/{check_id}", response_model=DeckAnalysisOut)
def open_check(
    check_id: str, db: Db, store: Checks, source_field: str = DEFAULT_PRICE_FIELD
) -> DeckAnalysisOut:
    """A saved check, compared against the collection as it is now."""
    check = _get(store, check_id)
    return _run(db.cursor(), store, check.text, source_field, existing=check)


@router.patch("/checks/{check_id}", response_model=DeckCheckOut)
def update_check(
    check_id: str, body: DeckCheckPatch, db: Db, store: Checks
) -> DeckCheckOut:
    """Rename a check, or turn its owned flag on or off.

    Turning the flag on puts the deck last in line for contested copies.
    """
    _get(store, check_id)
    name = body.name.strip() if body.name is not None else None
    if name == "":
        raise HTTPException(422, "A deck check needs a name.")
    check = store.update(check_id, name=name, owned=body.owned)
    assert check is not None
    return _check_out(check, db.cursor(), store)


@router.delete("/checks/{check_id}", status_code=204)
def delete_check(check_id: str, store: Checks) -> Response:
    """Forget a check. If it was flagged, its copies go to whoever is next."""
    if not store.delete(check_id):
        raise HTTPException(404, "No saved deck check with that id.")
    return Response(status_code=204)
