"""Fetch and cache YGOPRODeck's bulk card dumps.

One request covers every card — attributes, images and prices alike — plus one
more per configured language, which carries nothing but that language's card
names so the picker can be searched in it. They run when the user asks and at no
other time: not on import, not on a page load, not on a timer.

A localized dump is strictly an index. Its names are never stored on a collection
row, because the ledger's ``name`` column has to agree with the scanner's.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..config import (
    CACHE_DIR,
    CARDINFO_URL,
    CATALOGUE_LANGUAGES,
    DUMP_META_PATH,
    DUMP_PATH,
)
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

log = logging.getLogger(__name__)


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

    @property
    def card_names(self) -> Path:
        return self.root / "card_names.parquet"

    def localized(self, language: str) -> Path:
        return self.root / f"cardinfo.{language.lower()}.json"


@dataclass(frozen=True)
class DumpMeta:
    fetched_at: str  # UTC ISO-8601
    card_count: int
    byte_size: int
    source_url: str
    #: Languages whose name index was fetched alongside the English dump. Has a
    #: default so a cache written before this existed still loads.
    languages: list[str] = field(default_factory=list)

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
    # Keys the file lacks fall back to the field default, so a cache written by
    # an older version stays readable instead of failing the whole app on boot.
    return DumpMeta(**{k: raw[k] for k in DumpMeta.__dataclass_fields__ if k in raw})


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


def _cards_of(body: bytes, url: str) -> list[dict]:
    payload = json.loads(body)
    if "data" not in payload:
        raise ValueError(f"{url} returned no 'data' key; got keys {sorted(payload)}")
    return payload["data"]


def _write_atomically(path: Path, body: bytes) -> None:
    """Via a temp file, so an interrupted download never leaves a half-written
    cache that a later read would treat as complete."""
    tmp = path.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.replace(path)


async def fetch_dump(
    *,
    client: httpx.AsyncClient | None = None,
    force: bool = False,
    cache_dir: Path | None = None,
    languages: tuple[str, ...] | None = None,
) -> DumpMeta:
    """Download the dumps, cache them, and derive the catalogue tables.

    The English dump is the catalogue. Each language after it is fetched only for
    its card names, and a failure to get one is **not** fatal: the picker falls
    back to searching English, which is strictly better than refusing to refresh
    the catalogue because a translation was unavailable.

    Args:
        client: injected for tests; a transport-mocked client makes this offline.
        force: refetch even if a cached dump already exists. Without it, an
            existing cache is left alone — refreshing is the user's call, and
            the dumps are tens of megabytes.
        cache_dir: where the JSON, its metadata and the derived parquet go.
        languages: name indexes to fetch alongside. Defaults to the configured
            set; pass an empty tuple for English only.
    """
    paths = CachePaths(cache_dir or CACHE_DIR)
    wanted = CATALOGUE_LANGUAGES if languages is None else languages
    existing = load_meta(paths.meta)
    if existing is not None and not force:
        return existing

    # Before the first write, not after: the localized dumps land here too.
    paths.root.mkdir(parents=True, exist_ok=True)

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
    localized: dict[str, list[dict]] = {}
    try:
        await shared_limiter().acquire()
        response = await client.get(CARDINFO_URL, params=_NO_PARAMS)
        response.raise_for_status()
        body = response.content

        for language in wanted:
            try:
                await shared_limiter().acquire()
                extra = await client.get(CARDINFO_URL, params={"language": language})
                extra.raise_for_status()
                cards = _cards_of(extra.content, CARDINFO_URL)
            except Exception:
                # One unavailable translation must not cost the whole refresh.
                log.warning("no %s card names; search falls back to English", language,
                            exc_info=True)
                continue
            localized[language.upper()] = cards
            _write_atomically(paths.localized(language), extra.content)
    finally:
        if owns_client:
            await client.aclose()

    cards = _cards_of(body, CARDINFO_URL)
    _write_atomically(paths.dump, body)

    normalize_dump(
        cards,
        cards_path=paths.cards,
        card_sets_path=paths.card_sets,
        card_prices_path=paths.card_prices,
        card_names_path=paths.card_names,
        localized=localized,
    )

    # Metadata last: it is the marker that says the cache is complete and usable.
    meta = DumpMeta(
        fetched_at=datetime.now(timezone.utc).isoformat(),
        card_count=len(cards),
        byte_size=len(body),
        source_url=CARDINFO_URL,
        languages=sorted(localized),
    )
    paths.meta.write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")
    return meta
