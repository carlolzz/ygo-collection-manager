"""Which flagged deck holds which copies.

One rule: **first flagged wins.** Flagged checks claim copies in the order they
were flagged, each taking what it needs of what is left. Nothing is frozen: the
claims are worked out afresh from the collection as it is now, so unflagging or
deleting an early deck passes its copies on to the next one, and a copy added
to the collection goes to whoever is short.

A deck being checked sees what is left after every claim *ahead of it*: all of
them if it is not flagged, only the earlier ones if it is.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .compare import Ownership
from .history import DeckCheck

__all__ = ["CheckTotals", "held_elsewhere", "totals"]


def held_elsewhere(
    ownership: Ownership,
    flagged: Sequence[DeckCheck],
    current_id: str | None,
) -> dict[str, list[tuple[str, int]]]:
    """Per card_id, the copies decks ahead of ``current_id`` hold: (name, copies).

    Args:
        flagged: the flagged checks in claim order (``DeckCheckStore.flagged``).
        current_id: the check being looked at. If it is among ``flagged``, only
            the decks before it count; otherwise all of them do.
    """
    remaining: dict[str, int] = {}
    held: dict[str, list[tuple[str, int]]] = {}
    for check in flagged:
        if check.id == current_id:
            break
        for line in check.demand:
            if line.card_id not in remaining:
                remaining[line.card_id] = ownership.of(line.card_id, line.passcode)
            take = min(line.needed, remaining[line.card_id])
            if take:
                remaining[line.card_id] -= take
                held.setdefault(line.card_id, []).append((check.name, take))
    return held


@dataclass(frozen=True)
class CheckTotals:
    total_needed: int
    total_missing: int
    #: The copies this deck is holding; 0 unless its owned flag is on.
    copies_held: int


def totals(
    check: DeckCheck, ownership: Ownership, flagged: Sequence[DeckCheck]
) -> CheckTotals:
    """A saved check's counts as of now, without pricing anything."""
    held = held_elsewhere(ownership, flagged, check.id)
    needed = missing = got_total = 0
    for line in check.demand:
        owned = ownership.of(line.card_id, line.passcode)
        available = max(0, owned - sum(c for _, c in held.get(line.card_id, ())))
        got = min(line.needed, available)
        needed += line.needed
        missing += line.needed - got
        got_total += got
    return CheckTotals(
        total_needed=needed,
        total_missing=missing,
        copies_held=got_total if check.owned else 0,
    )
