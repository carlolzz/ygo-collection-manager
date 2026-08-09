"""Write the shortfall back out in the formats the user came from.

Knowing you are fourteen cards short is only half an answer; the other half is
getting that list into a shop's search box or back into EDOPro. So the analysis
is re-emitted two ways — a ``ydke://`` code and a plaintext list — both of which
``parse.py`` reads back, so a user can paste either one straight into the deck
check again and see the same shortfall.

Only the *missing* copies are written. Demand is aggregated across zones in
``compare.py``, so the copies you already own have to be spent back across the
zones here to work out where the gap actually falls.
"""

from __future__ import annotations

import base64
import struct
from collections.abc import Mapping, Sequence

from .compare import DeckCard
from .parse import ZONES

__all__ = ["encode_ydke", "missing_by_zone", "missing_text", "missing_ydke"]

_UINT32_MAX = 0xFFFFFFFF

_ZONE_HEADINGS = {"main": "Main Deck:", "extra": "Extra Deck:", "side": "Side Deck:"}


def missing_by_zone(zones: Mapping[str, int], owned: int) -> dict[str, int]:
    """Where a card's shortfall falls, zone by zone.

    Owned copies are spent in main-extra-side order, so a card run 2 in the main
    and 1 in the side with one copy owned is short one main and one side — not
    two of either. The results sum to the card's ``missing`` by construction.
    """
    remaining = owned
    short: dict[str, int] = {}
    for zone in ZONES:
        needed = zones.get(zone, 0)
        covered = min(needed, remaining)
        remaining -= covered
        short[zone] = needed - covered
    return short


def _as_uint32(passcode: str) -> int | None:
    """A ydke section is a uint32 array; anything that will not fit is dropped.

    Returning None rather than raising keeps one odd passcode from costing the
    user the whole code — the card still shows up in the text list.
    """
    if not passcode.isdigit():
        return None
    value = int(passcode)
    return value if value <= _UINT32_MAX else None


def encode_ydke(sections: Mapping[str, Sequence[int]]) -> str:
    """The inverse of ``parse_ydke``: one repeated passcode per copy, per zone."""
    parts = []
    for zone in ZONES:
        codes = list(sections.get(zone, ()))
        raw = struct.pack(f"<{len(codes)}I", *codes)
        parts.append(base64.b64encode(raw).decode("ascii"))
    return "ydke://" + "!".join(parts) + "!"


def missing_ydke(cards: Sequence[DeckCard]) -> str:
    """A ydke code holding only the copies the collection cannot cover."""
    sections: dict[str, list[int]] = {zone: [] for zone in ZONES}
    for card in cards:
        if not card.missing:
            continue
        code = _as_uint32(card.passcode)
        if code is None:
            continue
        for zone, count in missing_by_zone(card.zones, card.owned).items():
            sections[zone].extend([code] * count)

    if not any(sections.values()):
        return ""
    return encode_ydke(sections)


def missing_text(cards: Sequence[DeckCard]) -> str:
    """The same shortfall as a zone-grouped ``N Card Name`` list.

    Alphabetical within a zone rather than the table's most-missing-first order,
    because this one is read as a deck list and shopped down line by line.
    """
    grouped: dict[str, list[tuple[str, int]]] = {zone: [] for zone in ZONES}
    for card in cards:
        if not card.missing:
            continue
        for zone, count in missing_by_zone(card.zones, card.owned).items():
            if count:
                grouped[zone].append((card.name, count))

    blocks = []
    for zone in ZONES:
        entries = sorted(grouped[zone], key=lambda pair: pair[0].casefold())
        if not entries:
            continue
        lines = [_ZONE_HEADINGS[zone]]
        lines += [f"{count} {name}" for name, count in entries]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
