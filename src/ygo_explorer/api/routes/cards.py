"""Browsing and filtering the collection."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ...collection.schema import condition_rank_sql
from ..deps import Database, get_db
from ..filters import SORTS, CardFilters
from ..models import CardDetail, CardPage, CataloguePrinting, FilterOptions, OwnedRow
from ..projections import CARD_PROJECTION, SUMMARY_FIELDS, summaries

router = APIRouter(tags=["cards"])


def _filters(
    q: Annotated[str | None, Query(description="Name search; accent- and case-insensitive")] = None,
    condition: Annotated[list[str] | None, Query()] = None,
    edition: Annotated[list[str] | None, Query()] = None,
    language: Annotated[list[str] | None, Query()] = None,
    set_code: Annotated[list[str] | None, Query()] = None,
    set_name: Annotated[list[str] | None, Query()] = None,
    rarity: Annotated[list[str] | None, Query()] = None,
    type: Annotated[list[str] | None, Query()] = None,
    frame_type: Annotated[list[str] | None, Query()] = None,
    attribute: Annotated[list[str] | None, Query()] = None,
    race: Annotated[list[str] | None, Query(description="Raw upstream column; prefer the three below")] = None,
    monster_type: Annotated[list[str] | None, Query()] = None,
    spell_type: Annotated[list[str] | None, Query()] = None,
    trap_type: Annotated[list[str] | None, Query()] = None,
    archetype: Annotated[list[str] | None, Query()] = None,
    level_min: Annotated[int | None, Query(ge=0)] = None,
    level_max: Annotated[int | None, Query(ge=0)] = None,
    has_printing: Annotated[bool | None, Query(description="Rows with a set_code")] = None,
    in_catalogue: Annotated[bool | None, Query(description="Rows the dump knows")] = None,
) -> CardFilters:
    return CardFilters(
        q=q,
        condition=condition or [],
        edition=edition or [],
        language=language or [],
        set_code=set_code or [],
        set_name=set_name or [],
        rarity=rarity or [],
        type=type or [],
        frame_type=frame_type or [],
        attribute=attribute or [],
        race=race or [],
        monster_type=monster_type or [],
        spell_type=spell_type or [],
        trap_type=trap_type or [],
        archetype=archetype or [],
        level_min=level_min,
        level_max=level_max,
        has_printing=has_printing,
        in_catalogue=in_catalogue,
    )


@router.get("/cards", response_model=CardPage)
def list_cards(
    db: Annotated[Database, Depends(get_db)],
    filters: Annotated[CardFilters, Depends(_filters)],
    sort: Annotated[str, Query(description=f"One of: {', '.join(SORTS)}")] = "name",
    limit: Annotated[int, Query(ge=1, le=200)] = 60,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CardPage:
    """One item per distinct card; totals cover the whole filtered set."""
    if sort not in SORTS:
        raise HTTPException(422, f"Unknown sort '{sort}'. Expected one of {list(SORTS)}.")

    where, values = filters.where()
    con = db.cursor()

    total_cards, total_copies = con.execute(
        f"SELECT COUNT(DISTINCT passcode), COALESCE(SUM(quantity), 0) "
        f"FROM collection_enriched {where}",
        values,
    ).fetchone()

    rows = con.execute(
        f"""
        SELECT {CARD_PROJECTION}
        FROM collection_enriched {where}
        GROUP BY passcode
        ORDER BY {SORTS[sort]}
        LIMIT ? OFFSET ?
        """,
        [*values, limit, offset],
    ).fetchall()

    return CardPage(
        items=summaries(rows),
        total_cards=total_cards,
        total_copies=total_copies,
        limit=limit,
        offset=offset,
    )


@router.get("/cards/{passcode}", response_model=CardDetail)
def get_card(passcode: str, db: Annotated[Database, Depends(get_db)]) -> CardDetail:
    """Everything known about one owned card. Passcode is matched as a string."""
    con = db.cursor()
    row = con.execute(
        f"SELECT {CARD_PROJECTION}, any_value(description) AS description, "
        f"any_value(card_id) AS card_id "
        f"FROM collection_enriched WHERE passcode = ? GROUP BY passcode",
        [passcode],
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"Passcode {passcode} is not in the collection.")

    summary = dict(zip(SUMMARY_FIELDS, row))
    description, card_id = row[-2], row[-1]

    owned = con.execute(
        f"""
        SELECT set_code, set_name, rarity, condition, edition, language,
               quantity, notes, created_at, updated_at
        FROM collection_enriched
        WHERE passcode = ?
        ORDER BY {condition_rank_sql()}, edition, language
        """,
        [passcode],
    ).fetchall()
    rows = [
        OwnedRow(
            **dict(
                zip(
                    (
                        "set_code", "set_name", "rarity", "condition", "edition",
                        "language", "quantity", "notes", "created_at", "updated_at",
                    ),
                    r,
                )
            )
        )
        for r in owned
    ]

    # Printings the catalogue knows, with the owned ones flagged. Left empty when
    # the card is not in the dump at all — never guessed at.
    printings: list[CataloguePrinting] = []
    if card_id is not None:
        owned_codes = {r.set_code for r in rows if r.set_code}
        for s in con.execute(
            "SELECT set_code, set_name, set_rarity, set_price_usd FROM card_sets "
            "WHERE card_id = ? ORDER BY set_code",
            [card_id],
        ).fetchall():
            printings.append(
                CataloguePrinting(
                    set_code=s[0],
                    set_name=s[1],
                    set_rarity=s[2],
                    set_price_usd=float(s[3]) if s[3] is not None else None,
                    owned=s[0] in owned_codes,
                )
            )

    return CardDetail(**summary, description=description, rows=rows, printings=printings)


@router.get("/meta/filters", response_model=FilterOptions)
def filter_options(db: Annotated[Database, Depends(get_db)]) -> FilterOptions:
    """Distinct values actually present, so the filter bar is built from data."""
    con = db.cursor()

    def distinct(column: str, order: str | None = None) -> list[str]:
        clause = order or column
        return [
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT {column} FROM collection_enriched "
                f"WHERE {column} IS NOT NULL ORDER BY {clause}"
            ).fetchall()
        ]

    level_min, level_max = con.execute(
        "SELECT min(level), max(level) FROM collection_enriched"
    ).fetchone()

    return FilterOptions(
        condition=distinct("condition", condition_rank_sql()),
        edition=distinct("edition"),
        language=distinct("language"),
        rarity=distinct("rarity"),
        set_name=distinct("set_name"),
        type=distinct("type"),
        frame_type=distinct("frame_type"),
        attribute=distinct("attribute"),
        race=distinct("race"),
        monster_type=distinct("monster_type"),
        spell_type=distinct("spell_type"),
        trap_type=distinct("trap_type"),
        archetype=distinct("archetype"),
        level_min=level_min,
        level_max=level_max,
    )
