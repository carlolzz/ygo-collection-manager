"""One place that turns query parameters into SQL predicates.

Ownership filters come from the CSV and card-attribute filters from the joined
dump, but they compose through the same machinery and read identically from
outside — which is the point: a caller should not be able to tell which source a
filter came from.

Every value is bound, never interpolated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..text import fold

__all__ = ["CardFilters", "SORTS"]

# column -> the query parameter that filters it. Split only to document where
# each one originates; the generated SQL treats them alike.
_OWNERSHIP_COLUMNS = {
    "condition": "condition",
    "edition": "edition",
    "language": "language",
    "set_code": "set_code",
    "set_name": "set_name",
    "rarity": "rarity",
}
_CATALOGUE_COLUMNS = {
    "type": "type",
    "frame_type": "frame_type",
    "attribute": "attribute",
    # `race` is the raw upstream column, kept so older shared URLs still resolve.
    # The three below are its halves, split by card kind in collection_enriched.
    "race": "race",
    "monster_type": "monster_type",
    "spell_type": "spell_type",
    "trap_type": "trap_type",
    "archetype": "archetype",
}

#: Sort key -> SQL. NULLS LAST throughout so cards missing an attribute sink
#: rather than heading the list.
SORTS: dict[str, str] = {
    "name": "name COLLATE NOCASE ASC",
    "name_desc": "name COLLATE NOCASE DESC",
    "copies": "total_copies DESC, name COLLATE NOCASE ASC",
    "copies_asc": "total_copies ASC, name COLLATE NOCASE ASC",
    "newest": "first_acquired_at DESC, name COLLATE NOCASE ASC",
    "oldest": "first_acquired_at ASC, name COLLATE NOCASE ASC",
    "level": "level DESC NULLS LAST, name COLLATE NOCASE ASC",
    "atk": "atk DESC NULLS LAST, name COLLATE NOCASE ASC",
    # Aggregate rather than a projected column: the grid groups by passcode, and
    # the rank is constant within a group anyway.
    "card_type": "any_value(card_type_rank), name COLLATE NOCASE ASC",
}


@dataclass
class CardFilters:
    """A composed filter over ``collection_enriched``.

    Multi-valued filters are OR within a field and AND across fields, which is
    what a filter bar with checkbox groups implies.
    """

    q: str | None = None
    condition: list[str] = field(default_factory=list)
    edition: list[str] = field(default_factory=list)
    language: list[str] = field(default_factory=list)
    set_code: list[str] = field(default_factory=list)
    set_name: list[str] = field(default_factory=list)
    rarity: list[str] = field(default_factory=list)
    type: list[str] = field(default_factory=list)
    frame_type: list[str] = field(default_factory=list)
    attribute: list[str] = field(default_factory=list)
    race: list[str] = field(default_factory=list)
    monster_type: list[str] = field(default_factory=list)
    spell_type: list[str] = field(default_factory=list)
    trap_type: list[str] = field(default_factory=list)
    archetype: list[str] = field(default_factory=list)
    level_min: int | None = None
    level_max: int | None = None
    has_printing: bool | None = None
    in_catalogue: bool | None = None

    def where(self) -> tuple[str, list[object]]:
        """Return a WHERE clause and its bind values."""
        clauses: list[str] = []
        values: list[object] = []

        if self.q:
            # Both sides folded by the same function, so 'Necrovalley' finds
            # 'Nécrovalley'. name_folded was folded once, at load.
            clauses.append("name_folded LIKE ?")
            values.append(f"%{fold(self.q)}%")

        for column in {**_OWNERSHIP_COLUMNS, **_CATALOGUE_COLUMNS}:
            selected = getattr(self, column)
            if selected:
                placeholders = ", ".join("?" * len(selected))
                clauses.append(f"{column} IN ({placeholders})")
                values.extend(selected)

        if self.level_min is not None:
            clauses.append("level >= ?")
            values.append(self.level_min)
        if self.level_max is not None:
            clauses.append("level <= ?")
            values.append(self.level_max)

        if self.has_printing is not None:
            clauses.append(
                "set_code IS NOT NULL" if self.has_printing else "set_code IS NULL"
            )
        if self.in_catalogue is not None:
            clauses.append("in_catalogue" if self.in_catalogue else "NOT in_catalogue")

        if not clauses:
            return "", []
        return "WHERE " + " AND ".join(clauses), values

    def is_empty(self) -> bool:
        return self.where()[0] == ""
