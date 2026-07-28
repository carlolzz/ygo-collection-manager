"""Parse the deck formats EDOPro exports.

Three shapes, sniffed rather than declared, because a user pasting a list should
not have to tell us which button they pressed:

- **ydke** — ``ydke://<b64>!<b64>!<b64>!``. Each section is base64 of a
  little-endian ``uint32`` array of passcodes, and a card appearing three times
  means three copies.
- **.ydk** — ``#main`` / ``#extra`` / ``!side`` headers, one passcode per line.
- **plaintext** — ``Main Deck:`` / ``Extra Deck:`` / ``Side Deck:`` headers and
  ``N Card Name`` lines.

Parsing yields *references* — a passcode or a name, per zone, with a count.
Turning those into actual cards is ``resolve.py``'s job; a parser that quietly
dropped an unrecognized line would hide exactly what the user needs told.
"""

from __future__ import annotations

import base64
import binascii
import re
import struct
from collections import Counter
from dataclasses import dataclass, field

__all__ = ["Deck", "DeckEntry", "ParseError", "parse_deck", "ZONES"]

MAIN, EXTRA, SIDE = "main", "extra", "side"
ZONES = (MAIN, EXTRA, SIDE)

_YDKE_PREFIX = "ydke://"

# "3 Sabersaurus", "3x Sabersaurus", "3 x Sabersaurus"
_QUANTITY_LINE = re.compile(r"^\s*(\d+)\s*[xX]?\s+(.+?)\s*$")

_ZONE_HEADERS = {
    MAIN: re.compile(r"^\s*(#?main|main\s*deck)\b\s*:?\s*$", re.IGNORECASE),
    EXTRA: re.compile(r"^\s*(#?extra|extra\s*deck)\b\s*:?\s*$", re.IGNORECASE),
    SIDE: re.compile(r"^\s*([!#]?side|side\s*deck)\b\s*:?\s*$", re.IGNORECASE),
}

_YDK_COMMENT = re.compile(r"^\s*#(created|\s*$)", re.IGNORECASE)


class ParseError(ValueError):
    """The text is not a deck list in any recognized format."""


@dataclass(frozen=True)
class DeckEntry:
    """One line: a card reference and how many copies the zone asks for."""

    zone: str
    quantity: int
    passcode: str | None = None
    name: str | None = None

    @property
    def reference(self) -> str:
        return self.passcode or self.name or ""


@dataclass
class Deck:
    source_format: str
    entries: list[DeckEntry] = field(default_factory=list)

    def zone_counts(self) -> dict[str, int]:
        counts = dict.fromkeys(ZONES, 0)
        for entry in self.entries:
            counts[entry.zone] += entry.quantity
        return counts

    @property
    def total_cards(self) -> int:
        return sum(e.quantity for e in self.entries)


# --- ydke --------------------------------------------------------------------


def _decode_section(b64: str, zone: str) -> list[int]:
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ParseError(f"The {zone} section of the ydke code is not valid base64: {exc}")
    if len(raw) % 4:
        raise ParseError(
            f"The {zone} section of the ydke code is {len(raw)} bytes, which is not "
            "a whole number of 4-byte passcodes."
        )
    return list(struct.unpack(f"<{len(raw) // 4}I", raw))


def parse_ydke(text: str) -> Deck:
    body = text.strip()[len(_YDKE_PREFIX):]
    sections = body.split("!")
    if len(sections) < 3:
        raise ParseError(
            "A ydke code needs three '!'-separated sections (main, extra, side); "
            f"found {len(sections)}."
        )

    deck = Deck(source_format="ydke")
    for zone, section in zip(ZONES, sections[:3]):
        # Repeats are how copies are expressed, so count them.
        for passcode, quantity in Counter(_decode_section(section, zone)).items():
            deck.entries.append(
                DeckEntry(zone=zone, quantity=quantity, passcode=str(passcode))
            )

    if not deck.entries:
        # Three empty sections is well-formed base64 and an empty deck. Saying
        # so beats reporting that nothing is missing from a list of nothing.
        raise ParseError("That ydke code decodes to an empty deck — no cards in any zone.")
    return deck


# --- .ydk and plaintext ------------------------------------------------------


def _zone_for(line: str) -> str | None:
    for zone, pattern in _ZONE_HEADERS.items():
        if pattern.match(line):
            return zone
    return None


def parse_lines(text: str) -> Deck:
    """Handles both .ydk (bare passcodes) and plaintext (``N Name``).

    The two differ only in what a line holds, and a list can legitimately mix
    them, so one pass reads both.
    """
    zone = MAIN
    numeric = Counter()  # (zone, passcode) -> copies, for bare .ydk lines
    deck = Deck(source_format="plaintext")
    saw_named = False
    saw_numeric = False

    for raw_line in text.splitlines():
        line = raw_line.strip().lstrip("﻿")
        if not line or _YDK_COMMENT.match(line):
            continue

        header = _zone_for(line)
        if header is not None:
            zone = header
            continue

        # A bare number is a .ydk passcode line; repeats mean copies.
        if line.isdigit():
            numeric[(zone, line)] += 1
            saw_numeric = True
            continue

        match = _QUANTITY_LINE.match(line)
        if match:
            quantity, name = int(match.group(1)), match.group(2).strip()
            if quantity < 1:
                continue
            deck.entries.append(DeckEntry(zone=zone, quantity=quantity, name=name))
            saw_named = True
            continue

        # A name with no leading count is one copy.
        deck.entries.append(DeckEntry(zone=zone, quantity=1, name=line))
        saw_named = True

    for (zone_key, passcode), quantity in numeric.items():
        deck.entries.append(
            DeckEntry(zone=zone_key, quantity=quantity, passcode=passcode)
        )

    if not deck.entries:
        raise ParseError(
            "No deck lines found. Expected either 'N Card Name' lines, bare "
            "passcodes, or a ydke:// code."
        )

    if saw_numeric and not saw_named:
        deck.source_format = "ydk"
    return deck


def parse_deck(text: str) -> Deck:
    """Sniff the format and parse. Raises ParseError on anything unrecognized."""
    if not text or not text.strip():
        raise ParseError("Nothing to parse — the deck list is empty.")
    if text.strip().lower().startswith(_YDKE_PREFIX):
        return parse_ydke(text)
    return parse_lines(text)
