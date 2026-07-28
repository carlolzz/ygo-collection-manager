"""Aggregate views over the collection."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ...collection.schema import condition_rank_sql
from ..deps import Database, get_db
from ..models import Bucket, Stats, TimeBucket
from ..projections import CARD_PROJECTION, summaries

router = APIRouter(tags=["stats"])


def _buckets(con, column: str, order: str, limit: int | None = None) -> list[Bucket]:
    """Copies and distinct cards per value of one column.

    Both counts, always: a bar chart labelled only "count" is precisely the
    ambiguity the collection's shape punishes.
    """
    clause = f"LIMIT {limit}" if limit else ""
    rows = con.execute(
        f"""
        SELECT {column} AS key,
               SUM(quantity)::BIGINT AS total_copies,
               COUNT(DISTINCT passcode)::BIGINT AS distinct_cards
        FROM collection_enriched
        GROUP BY {column}
        ORDER BY {order}
        {clause}
        """
    ).fetchall()
    return [Bucket(key=r[0], total_copies=r[1], distinct_cards=r[2]) for r in rows]


@router.get("/stats", response_model=Stats)
def stats(
    db: Annotated[Database, Depends(get_db)],
    top: Annotated[int, Query(ge=1, le=100, description="Size of the long tail")] = 20,
) -> Stats:
    con = db.cursor()

    totals = con.execute(
        """
        SELECT
            COALESCE(SUM(quantity), 0)::BIGINT,
            COUNT(DISTINCT passcode)::BIGINT,
            COUNT(*)::BIGINT,
            COUNT(DISTINCT set_name)::BIGINT,
            COALESCE(SUM(quantity) FILTER (WHERE set_code IS NULL), 0)::BIGINT
        FROM collection_enriched
        """
    ).fetchone()

    acquisitions = [
        TimeBucket(period=r[0], total_copies=r[1], distinct_cards=r[2])
        for r in con.execute(
            """
            SELECT strftime(created_at, '%Y-%m') AS period,
                   SUM(quantity)::BIGINT,
                   COUNT(DISTINCT passcode)::BIGINT
            FROM collection_enriched
            GROUP BY period
            ORDER BY period
            """
        ).fetchall()
    ]

    most_held = summaries(
        con.execute(
            f"""
            SELECT {CARD_PROJECTION}
            FROM collection_enriched
            GROUP BY passcode
            ORDER BY total_copies DESC, name COLLATE NOCASE ASC
            LIMIT ?
            """,
            [top],
        ).fetchall()
    )

    return Stats(
        total_copies=totals[0],
        distinct_cards=totals[1],
        collection_rows=totals[2],
        sets_represented=totals[3],
        copies_without_printing=totals[4],
        by_condition=_buckets(con, "condition", condition_rank_sql()),
        by_edition=_buckets(con, "edition", "edition"),
        by_language=_buckets(con, "language", "total_copies DESC, language"),
        by_type=_buckets(con, "type", "total_copies DESC, type"),
        by_attribute=_buckets(con, "attribute", "total_copies DESC, attribute"),
        by_archetype=_buckets(con, "archetype", "total_copies DESC, archetype", 30),
        by_set=_buckets(con, "set_name", "total_copies DESC, set_name", 30),
        acquisitions_by_month=acquisitions,
        most_held=most_held,
    )
