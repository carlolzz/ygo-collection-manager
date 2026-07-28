"""Turn parsed deck references into catalogue cards.

Two lookups, both against the cached dump:

- **by passcode** — the ``cards`` table is already alt-art aware, so a ydke code
  referencing an alternate artwork resolves to the card it belongs to.
- **by name** — folded with the same ``text.fold`` the collection uses, so
  accents and case do not matter.

Anything that resolves to nothing is returned as unresolved. A silently dropped
line would understate what the deck needs, which is the one number the feature
exists to produce.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from ..text import fold
from .parse import Deck, DeckEntry

__all__ = ["ResolvedEntry", "Resolution", "resolve_deck"]


@dataclass(frozen=True)
class ResolvedEntry:
    zone: str
    quantity: int
    card_id: str
    passcode: str
    name: str


@dataclass
class Resolution:
    resolved: list[ResolvedEntry]
    unresolved: list[DeckEntry]

    @property
    def unresolved_labels(self) -> list[str]:
        return [e.reference for e in self.unresolved]


def _by_passcode(con: duckdb.DuckDBPyConnection, passcodes: set[str]) -> dict[str, tuple[str, str]]:
    """passcode -> (card_id, name). Matches on the canonical key.

    A deck's passcodes come from EDOPro as plain integers while the collection's
    may carry leading zeros, so both sides go through the same normalization the
    loader uses.
    """
    if not passcodes:
        return {}
    placeholders = ", ".join("?" * len(passcodes))
    keys = [p.lstrip("0") or "0" for p in passcodes]
    rows = con.execute(
        f"SELECT passcode_key, any_value(card_id), any_value(name) FROM cards "
        f"WHERE passcode_key IN ({placeholders}) GROUP BY passcode_key",
        keys,
    ).fetchall()
    found = {r[0]: (r[1], r[2]) for r in rows}
    return {p: found[p.lstrip("0") or "0"] for p in passcodes if (p.lstrip("0") or "0") in found}


def _by_name(con: duckdb.DuckDBPyConnection, names: set[str]) -> dict[str, tuple[str, str, str]]:
    """folded name -> (card_id, passcode, name)."""
    if not names:
        return {}
    folded = {fold(n) for n in names}
    placeholders = ", ".join("?" * len(folded))
    rows = con.execute(
        f"""
        SELECT name_folded, any_value(card_id), any_value(passcode), any_value(name)
        FROM cards
        WHERE name_folded IN ({placeholders}) AND NOT is_alternate_art
        GROUP BY name_folded
        """,
        list(folded),
    ).fetchall()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def resolve_deck(con: duckdb.DuckDBPyConnection, deck: Deck) -> Resolution:
    """Resolve every entry, keeping the failures."""
    passcodes = {e.passcode for e in deck.entries if e.passcode}
    names = {e.name for e in deck.entries if e.name}

    passcode_map = _by_passcode(con, passcodes)
    name_map = _by_name(con, names)

    resolved: list[ResolvedEntry] = []
    unresolved: list[DeckEntry] = []

    for entry in deck.entries:
        if entry.passcode and entry.passcode in passcode_map:
            card_id, name = passcode_map[entry.passcode]
            resolved.append(
                ResolvedEntry(entry.zone, entry.quantity, card_id, entry.passcode, name)
            )
        elif entry.name and fold(entry.name) in name_map:
            card_id, passcode, name = name_map[fold(entry.name)]
            resolved.append(
                ResolvedEntry(entry.zone, entry.quantity, card_id, passcode, name)
            )
        else:
            unresolved.append(entry)

    return Resolution(resolved=resolved, unresolved=unresolved)
