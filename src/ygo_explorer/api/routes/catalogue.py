"""Catalogue provenance, lookup, and the one endpoint allowed to touch the network.

``/refresh`` is that one. The two lookup endpoints below read the cached parquet
and nothing else, which is what lets the card picker search 14,000 cards while
the app keeps its promise that nothing reaches YGOPRODeck without a click.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ...catalogue.dump import fetch_dump, load_meta
from ...config import BASE_LANGUAGE, CATALOGUE_LANGUAGES
from ...text import fold
from ..deps import Database, get_db
from ..models import CatalogueCard, CataloguePrinting, CatalogueStatus

router = APIRouter(prefix="/catalogue", tags=["catalogue"])

#: The languages the picker offers to search in — English plus whatever extra
#: name indexes are configured. What is *cached* is a separate question, and the
#: status reports both: the difference is a language the UI must offer as
#: unavailable rather than let someone select and find nothing in.
SEARCH_LANGUAGES: list[str] = [
    BASE_LANGUAGE,
    *(language.upper() for language in CATALOGUE_LANGUAGES),
]


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
        languages=[lang.upper() for lang in meta.languages] if meta else [],
        search_languages=SEARCH_LANGUAGES,
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


def _passcode_key(passcode: str) -> str:
    """The loader's canonical form, so a typed ``00004041`` finds ``4041``."""
    return passcode.lstrip("0") or "0"


#: How many copies of this card are already owned, and how many printings the
#: dump lists. Both are scalar subqueries because the alternative is two joins
#: and a GROUP BY that would have to be right about which count it is producing.
#:
#: Ownership is counted per *card*, not per passcode — the same rule the deck
#: check holds to. Searching an alternate artwork's id must report the copies you
#: hold of that card, not zero because they were logged under the base id.
_COUNTS = """
    (SELECT COUNT(*) FROM card_sets s WHERE s.card_id = k.card_id) AS printing_count,
    (SELECT COALESCE(SUM(c.quantity), 0)
       FROM collection c JOIN cards ck ON ck.passcode_key = c.passcode_key
      WHERE ck.card_id = k.card_id)                                AS owned_copies
"""

# LIKE has two wildcards of its own, and a card name may legitimately contain
# neither — but a user typing one must search for the character, not the pattern.
_LIKE_ESCAPE = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


@router.get("/cards", response_model=list[CatalogueCard])
def search_cards(
    db: Annotated[Database, Depends(get_db)],
    q: Annotated[str, Query(min_length=1, description="A card name, or a passcode")],
    language: Annotated[
        str | None,
        Query(description="Scope the name search to one language. Omit to search all."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
) -> list[CatalogueCard]:
    """Find cards in the cached dump, owned or not. No network, ever.

    All digits is read as a passcode and matched exactly on the canonical key —
    including alternate-artwork ids, since that is the number actually printed on
    the card in hand. A passcode is a number rather than a name, so ``language``
    does not apply to it: the same digits find the same card whichever language
    is selected.

    Anything else is a substring search on the folded name, so ``necrovalley``
    finds ``Nécrovalley`` and ``Mago Nero`` finds Dark Magician. Passing
    ``language`` scopes that search to one language's names and nothing else —
    a card the localized dump does not cover is then not findable by name, which
    is the point: someone entering an Italian card is looking for Italian names.
    Omitting it searches every cached language at once.

    A card matched by a name other than its English one reports that name in
    ``matched_name``, because a picker that answers an Italian query with only
    English names looks like it found the wrong card. The English name is still
    what is returned as ``name`` and what gets written to the ledger — the
    collection's names have to agree with the scanner's.

    Alternate artworks are excluded from the name search, so one card appears in
    the list once.
    """
    con = db.cursor()
    query = q.strip()
    if not query:
        return []

    if query.isdigit():
        rows = con.execute(
            f"SELECT any_value(k.passcode), any_value(k.name), any_value(k.type), {_COUNTS}, "
            f"NULL, NULL "
            f"FROM cards k WHERE k.passcode_key = ? "
            f"GROUP BY k.card_id, k.passcode_key ORDER BY any_value(k.name) LIMIT ?",
            [_passcode_key(query), limit],
        ).fetchall()
    else:
        exact = fold(query)
        folded = exact.translate(_LIKE_ESCAPE)
        # Only the clause is interpolated; the code itself is bound, so an
        # unknown language matches nothing rather than reaching the SQL. One
        # statement with an optional predicate, rather than two to keep in step.
        wanted = language.strip().upper() if language and language.strip() else None
        scope = "AND language = ?" if wanted else ""
        rows = con.execute(
            f"""
            WITH hit AS (
                SELECT
                    card_id,
                    -- Exact match, then names that start with the query, then the
                    -- rest. Typing "dark magician" should not bury it under forty
                    -- archetype cards.
                    min(CASE WHEN name_folded = ? THEN 0
                             WHEN name_folded LIKE ? ESCAPE '\\' THEN 1
                             ELSE 2 END)                                AS rank,
                    -- The name that actually matched, so an Italian search can
                    -- show what it found. arg_min ties it to the best-ranked row
                    -- rather than picking an arbitrary language's. Under a scope
                    -- the group holds one language, so it simply returns that.
                    arg_min(name, CASE WHEN language = ? THEN 0 ELSE 1 END)
                                                                        AS hit_name,
                    arg_min(language, CASE WHEN language = ? THEN 0 ELSE 1 END)
                                                                        AS hit_language
                FROM card_names
                WHERE name_folded LIKE ? ESCAPE '\\'
                {scope}
                GROUP BY card_id
            )
            SELECT any_value(k.passcode), any_value(k.name), any_value(k.type), {_COUNTS},
                   any_value(h.hit_name), any_value(h.hit_language)
            FROM cards k JOIN hit h ON h.card_id = k.card_id
            WHERE NOT k.is_alternate_art
            GROUP BY k.card_id, k.passcode_key
            ORDER BY min(h.rank), any_value(k.name)
            LIMIT ?
            """,
            [
                exact,
                f"{folded}%",
                BASE_LANGUAGE,
                BASE_LANGUAGE,
                f"%{folded}%",
                *([wanted] if wanted else []),
                limit,
            ],
        ).fetchall()

    return [
        CatalogueCard(
            passcode=r[0],
            name=r[1],
            type=r[2],
            printing_count=r[3],
            owned_copies=r[4],
            # Only worth saying when it differs from the name shown.
            matched_name=r[5] if r[5] and r[5] != r[1] else None,
            matched_language=r[6] if r[5] and r[5] != r[1] else None,
        )
        for r in rows
    ]


@router.get("/cards/{passcode}/printings", response_model=list[CataloguePrinting])
def card_printings(
    passcode: str, db: Annotated[Database, Depends(get_db)]
) -> list[CataloguePrinting]:
    """Every printing the dump lists for a card, with the owned ones flagged.

    Kept off the search response on purpose: a card can have forty printings, and
    twenty-five results carrying all of theirs is a payload nobody reads.
    """
    con = db.cursor()
    key = _passcode_key(passcode)

    row = con.execute(
        "SELECT any_value(card_id) FROM cards WHERE passcode_key = ?", [key]
    ).fetchone()
    if row is None or row[0] is None:
        raise HTTPException(404, f"Passcode {passcode} is not in the cached card data.")

    # Owned printings of the *card*, so an alternate artwork's id still flags the
    # printings held under the base id. Same rule as the counts above.
    owned = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT c.set_code FROM collection c "
            "JOIN cards k ON k.passcode_key = c.passcode_key "
            "WHERE k.card_id = ? AND c.set_code IS NOT NULL",
            [row[0]],
        ).fetchall()
    }

    return [
        CataloguePrinting(
            set_code=s[0],
            set_name=s[1],
            set_rarity=s[2],
            set_price_usd=float(s[3]) if s[3] is not None else None,
            owned=s[0] in owned,
        )
        for s in con.execute(
            "SELECT set_code, set_name, set_rarity, set_price_usd FROM card_sets "
            "WHERE card_id = ? ORDER BY set_code",
            [row[0]],
        ).fetchall()
    ]
