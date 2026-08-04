"""Deck import: what a list needs, what is owned, and what the gap costs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...config import DEFAULT_PRICE_FIELD
from ...deck.compare import analyze_deck
from ...deck.parse import ParseError, parse_deck
from ..deps import Database, get_db
from ..models import DeckAnalysisOut, DeckCardOut, MoneyOut

router = APIRouter(prefix="/deck", tags=["deck"])


class DeckRequest(BaseModel):
    text: str = Field(
        description="A ydke:// code, a .ydk file's contents, or a plaintext "
        "decklist. The format is detected, not declared.",
        min_length=1,
    )
    source_field: str = DEFAULT_PRICE_FIELD


@router.post("/analyze", response_model=DeckAnalysisOut)
def analyze(
    body: DeckRequest, db: Annotated[Database, Depends(get_db)]
) -> DeckAnalysisOut:
    """Compare a deck list against the collection.

    Local only — the prices come from the cached dump, so this touches no
    network however long the list is.
    """
    try:
        deck = parse_deck(body.text)
    except ParseError as exc:
        raise HTTPException(422, str(exc)) from None

    try:
        analysis = analyze_deck(db.cursor(), deck, source_field=body.source_field)
    except ValueError as exc:
        # An unknown price field is the caller's mistake, not a server fault.
        raise HTTPException(422, str(exc)) from None

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
            )
            for c in analysis.cards
        ],
    )
