"""Fetch and cache YGOPRODeck's bulk card dump.

One request covers every card — attributes, images and prices alike — so this is
the only network call the read side of the app ever needs. It runs when the user
asks for it and at no other time: not on import, not on a page load, not on a
timer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..config import CACHE_DIR, CARDINFO_URL, DUMP_META_PATH, DUMP_PATH
from ..net.limiter import shared_limiter
from .normalize import normalize_dump

__all__ = [
    "DumpMeta",
    "fetch_dump",
    "load_meta",
    "dump_age_days",
    "read_dump",
    "CachePaths",
]

# The guide is explicit: "The only way to return all cards now is by having 0
# parameters in the request."
_NO_PARAMS: dict[str, str] = {}

_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)


@dataclass(frozen=True)
class CachePaths:
    """Every file a dump refresh touches, derived from one directory.

    Grouped so a caller — a test especially — cannot redirect the JSON but leave
    the derived parquet writing into the real cache.
    """

    root: Path

    @property
    def dump(self) -> Path:
        return self.root / "cardinfo.json"

    @property
    def meta(self) -> Path:
        return self.root / "cardinfo.meta.json"

    @property
    def cards(self) -> Path:
        return self.root / "cards.parquet"

    @property
    def card_sets(self) -> Path:
        return self.root / "card_sets.parquet"

    @property
    def card_prices(self) -> Path:
        return self.root / "card_prices.parquet"


@dataclass(frozen=True)
class DumpMeta:
    fetched_at: str  # UTC ISO-8601
    card_count: int
    byte_size: int
    source_url: str

    @property
    def fetched_at_utc(self) -> datetime:
        return datetime.fromisoformat(self.fetched_at)

    @property
    def age_days(self) -> float:
        delta = datetime.now(timezone.utc) - self.fetched_at_utc
        return delta.total_seconds() / 86400.0


def load_meta(meta_path: Path = DUMP_META_PATH) -> DumpMeta | None:
    """The cached dump's provenance, or None if nothing has been fetched."""
    if not meta_path.is_file():
        return None
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    return DumpMeta(**{k: raw[k] for k in DumpMeta.__dataclass_fields__})


def dump_age_days(meta_path: Path = DUMP_META_PATH) -> float | None:
    meta = load_meta(meta_path)
    return None if meta is None else meta.age_days


def read_dump(dump_path: Path = DUMP_PATH) -> list[dict]:
    """The cached dump's card list. Raises if it was never fetched."""
    if not dump_path.is_file():
        raise FileNotFoundError(
            f"No cached card dump at {dump_path}. Run 'ygo-explorer refresh-dump' "
            "or POST /api/catalogue/refresh."
        )
    payload = json.loads(dump_path.read_text(encoding="utf-8"))
    return payload["data"]


async def fetch_dump(
    *,
    client: httpx.AsyncClient | None = None,
    force: bool = False,
    cache_dir: Path = CACHE_DIR,
) -> DumpMeta:
    """Download the dump, cache it, and derive the catalogue tables.

    Args:
        client: injected for tests; a transport-mocked client makes this offline.
        force: refetch even if a cached dump already exists. Without it, an
            existing cache is left alone — refreshing is the user's call, and
            the dump is several megabytes.
        cache_dir: where the JSON, its metadata and the derived parquet go.
    """
    paths = CachePaths(cache_dir)
    existing = load_meta(paths.meta)
    if existing is not None and not force:
        return existing

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
    try:
        await shared_limiter().acquire()
        response = await client.get(CARDINFO_URL, params=_NO_PARAMS)
        response.raise_for_status()
        body = response.content
    finally:
        if owns_client:
            await client.aclose()

    payload = json.loads(body)
    if "data" not in payload:
        raise ValueError(
            f"{CARDINFO_URL} returned no 'data' key; got keys {sorted(payload)}"
        )
    cards = payload["data"]

    paths.root.mkdir(parents=True, exist_ok=True)
    # Written via a temp file so an interrupted download never leaves a
    # half-parsed cache that later reads would treat as complete.
    tmp = paths.dump.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.replace(paths.dump)

    normalize_dump(
        cards,
        cards_path=paths.cards,
        card_sets_path=paths.card_sets,
        card_prices_path=paths.card_prices,
    )

    # Metadata last: it is the marker that says the cache is complete and usable.
    meta = DumpMeta(
        fetched_at=datetime.now(timezone.utc).isoformat(),
        card_count=len(cards),
        byte_size=len(body),
        source_url=CARDINFO_URL,
    )
    paths.meta.write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")
    return meta
