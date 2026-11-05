"""Saved deck checks, and which of them hold their copies.

Every check is kept, so a deck checked last week can be reopened rather than
re-pasted. A check whose **owned** flag is on holds the copies it uses: other
checks no longer count those copies as owned (see ``reserve``).

Kept as one small JSON file in the data directory, next to the collection
export but never inside it — the CSV belongs to the scanner app, and a flag is
this app's own record. Every change is written straight through, via a temp
file, so a crash loses at most the change being made.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import config

__all__ = ["DemandLine", "DeckCheck", "DeckCheckStore", "text_hash"]

log = logging.getLogger(__name__)

_FORMAT_VERSION = 1


@dataclass(frozen=True)
class DemandLine:
    """What one card of a saved deck calls for, across all three zones."""

    card_id: str
    passcode: str
    name: str
    needed: int


@dataclass(frozen=True)
class DeckCheck:
    id: str
    name: str
    text: str
    text_hash: str
    source_format: str
    created_at: datetime
    checked_at: datetime
    owned: bool = False
    #: When the owned flag was last turned on. Decides who wins a contested
    #: copy: the earlier flag does.
    flagged_at: datetime | None = None
    demand: tuple[DemandLine, ...] = field(default_factory=tuple)

    def to_json(self) -> dict:
        body = asdict(self)
        body["created_at"] = self.created_at.isoformat()
        body["checked_at"] = self.checked_at.isoformat()
        body["flagged_at"] = self.flagged_at.isoformat() if self.flagged_at else None
        body["demand"] = [asdict(d) for d in self.demand]
        return body

    @classmethod
    def from_json(cls, body: dict) -> "DeckCheck":
        flagged = body.get("flagged_at")
        return cls(
            id=body["id"],
            name=body["name"],
            text=body["text"],
            text_hash=body.get("text_hash") or text_hash(body["text"]),
            source_format=body["source_format"],
            created_at=datetime.fromisoformat(body["created_at"]),
            checked_at=datetime.fromisoformat(body["checked_at"]),
            owned=bool(body.get("owned", False)),
            flagged_at=datetime.fromisoformat(flagged) if flagged else None,
            demand=tuple(DemandLine(**d) for d in body.get("demand", [])),
        )


def _normalize(text: str) -> str:
    """The same list however it was pasted: line endings and trailing space
    are the clipboard's, not the deck's."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


def _default_name(when: datetime) -> str:
    return f"Deck check · {when.day} {when:%b %Y, %H:%M}"


class DeckCheckStore:
    """The saved checks, held in memory and written through to ``path``.

    Shared by every request, and FastAPI runs sync endpoints on a thread pool,
    so every read-modify-write happens under one lock.
    """

    def __init__(self, path: Path | None = None) -> None:
        # Read at construction, not import, so a test can point it elsewhere.
        self.path = path if path is not None else config.DECK_CHECKS_PATH
        self._lock = threading.Lock()
        self._checks: dict[str, DeckCheck] = self._load()

    # --- persistence ---------------------------------------------------------

    def _load(self) -> dict[str, DeckCheck]:
        if not self.path.is_file():
            return {}
        try:
            body = json.loads(self.path.read_text(encoding="utf-8"))
            checks = [DeckCheck.from_json(c) for c in body.get("checks", [])]
        except (ValueError, KeyError, TypeError):
            # Starting empty would overwrite the file on the next check and
            # lose every flag in it. Set it aside, intact, and say so.
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            aside = self.path.with_name(f"{self.path.name}.unreadable-{stamp}")
            self.path.replace(aside)
            log.warning("deck checks file was unreadable; moved it to %s", aside)
            return {}
        return {c.id: c for c in checks}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "version": _FORMAT_VERSION,
            "checks": [c.to_json() for c in self._checks.values()],
        }
        tmp = self.path.with_name(self.path.name + ".part")
        tmp.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    # --- reading -------------------------------------------------------------

    def list(self) -> list[DeckCheck]:
        """Most recently checked first."""
        with self._lock:
            return sorted(self._checks.values(), key=lambda c: c.checked_at, reverse=True)

    def get(self, check_id: str) -> DeckCheck | None:
        with self._lock:
            return self._checks.get(check_id)

    def flagged(self) -> list[DeckCheck]:
        """The checks holding copies, in the order they claim them."""
        with self._lock:
            held = [c for c in self._checks.values() if c.owned]
        return sorted(held, key=lambda c: (c.flagged_at or c.created_at, c.created_at))

    # --- writing -------------------------------------------------------------

    def record(
        self, text: str, source_format: str, demand: list[DemandLine]
    ) -> DeckCheck:
        """Save a check that was just run.

        The same list checked again is the same check: it is brought up to
        date, keeping its name and its flag, rather than added a second time.
        """
        digest = text_hash(text)
        now = datetime.now(timezone.utc)
        with self._lock:
            existing = next(
                (c for c in self._checks.values() if c.text_hash == digest), None
            )
            if existing is not None:
                check = replace(
                    existing,
                    source_format=source_format,
                    checked_at=now,
                    demand=tuple(demand),
                )
            else:
                check = DeckCheck(
                    id=uuid.uuid4().hex,
                    name=_default_name(now),
                    text=text,
                    text_hash=digest,
                    source_format=source_format,
                    created_at=now,
                    checked_at=now,
                    demand=tuple(demand),
                )
            self._checks[check.id] = check
            self._save()
            return check

    def refresh_demand(self, check_id: str, demand: list[DemandLine]) -> DeckCheck | None:
        """Re-resolve a saved list without counting it as a new check.

        Opening a check must not reorder the history under the cursor, so the
        ``checked_at`` it is sorted by stays put.
        """
        with self._lock:
            check = self._checks.get(check_id)
            if check is None:
                return None
            if check.demand != tuple(demand):
                check = replace(check, demand=tuple(demand))
                self._checks[check_id] = check
                self._save()
            return check

    def update(
        self, check_id: str, *, name: str | None = None, owned: bool | None = None
    ) -> DeckCheck | None:
        with self._lock:
            check = self._checks.get(check_id)
            if check is None:
                return None
            if name is not None:
                check = replace(check, name=name)
            if owned is not None and owned != check.owned:
                # Re-flagging puts the deck at the back of the queue: it is a
                # new claim, made after everyone already holding copies.
                check = replace(
                    check, owned=owned, flagged_at=self._next_flag_time() if owned else None
                )
            self._checks[check_id] = check
            self._save()
            return check

    def _next_flag_time(self) -> datetime:
        """Now, but strictly after every flag already set.

        The flag time *is* the queue order, and the Windows clock can hand two
        quick flags the same instant — which would leave who wins a contested
        copy to a tie-break nobody chose.
        """
        now = datetime.now(timezone.utc)
        latest = max(
            (c.flagged_at for c in self._checks.values() if c.flagged_at), default=None
        )
        if latest is not None and now <= latest:
            now = latest + timedelta(microseconds=1)
        return now

    def delete(self, check_id: str) -> bool:
        with self._lock:
            if self._checks.pop(check_id, None) is None:
                return False
            self._save()
            return True
