"""The per-card projection, defined once.

The grid, the detail view and the long tail all render the same card shape, so
they read it from the same SQL — otherwise the three drift and only one of them
is right.
"""

from __future__ import annotations

from .models import CardSummary

__all__ = ["CARD_PROJECTION", "SUMMARY_FIELDS", "summaries"]

# Grouped by passcode. any_value is safe: every column below is functionally
# dependent on the passcode, since it comes from the card, not the owned row.
CARD_PROJECTION = """
    passcode,
    any_value(name)                     AS name,
    bool_or(in_catalogue)               AS in_catalogue,
    any_value(type)                     AS type,
    any_value(frame_type)               AS frame_type,
    any_value(attribute)                AS attribute,
    any_value(race)                     AS race,
    any_value(archetype)                AS archetype,
    any_value(atk)                      AS atk,
    any_value(defense)                  AS defense,
    any_value(level)                    AS level,
    any_value(image_url_small)          AS source_image_url,
    SUM(quantity)::BIGINT               AS total_copies,
    COUNT(*)::BIGINT                    AS row_count,
    COUNT(DISTINCT set_code)::BIGINT    AS printing_count,
    min(created_at)                     AS first_acquired_at,
    -- The one owned-row column here that is not functionally dependent on the
    -- passcode: the same card is often held in several languages, so it is
    -- collected rather than picked. Sorted for a stable order across requests.
    COALESCE(list_sort(list_distinct(
        list(language) FILTER (WHERE nullif(trim(language), '') IS NOT NULL)
    )), []::VARCHAR[])                  AS languages
"""

SUMMARY_FIELDS: tuple[str, ...] = (
    "passcode",
    "name",
    "in_catalogue",
    "type",
    "frame_type",
    "attribute",
    "race",
    "archetype",
    "atk",
    "defense",
    "level",
    "source_image_url",
    "total_copies",
    "row_count",
    "printing_count",
    "first_acquired_at",
    "languages",
)


def summaries(rows: list[tuple]) -> list[CardSummary]:
    """Map rows of CARD_PROJECTION onto the response model."""
    return [CardSummary(**dict(zip(SUMMARY_FIELDS, row))) for row in rows]
