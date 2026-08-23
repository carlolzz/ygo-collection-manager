"""Fetch and cache YGOPRODeck's bulk card dumps.

One request covers every card — attributes, images and prices alike — plus one
more per configured language, which carries nothing but that language's card
names so the picker can be searched in it. They run when the user asks and at no
other time: not on import, not on a page load, not on a timer.

A localized dump is strictly an index. Its names are never stored on a collection
row, because the ledger's ``name`` column has to agree with the scanner's.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
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
    "DumpProgress",
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

#: How much has to land before progress is reported again. Tens of megabytes
#: arrive in chunks of a few kilobytes, and a caller that recomputes an estimate
#: per chunk is doing thousands of times the work the screen can show.
_PROGRESS_STEP = 256 * 1024

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
class DumpProgress:
    """Where a refresh has got to, reported as it goes.

    Deliberately raw: bytes and step numbers, no percentage and no estimate. The
    caller knows whether it is drawing a bar, writing a log line or doing
    nothing, and only it can say how the phases should be weighed against each
    other.
    """

    #: ``cards`` and ``names`` are downloads; ``building`` derives the parquet
    #: and has no byte count to report, only a start.
    phase: str
    #: The language being fetched, during ``names``.
    language: str | None
    #: 1-based, over ``steps``. Both count the *downloads* — the build is not one
    #: of them, having no size to weigh against the others, and reports the last
    #: download's number rather than a step of its own.
    step: int
    steps: int
    #: Bytes off the wire for *this* step. Not cumulative: the caller adds up
    #: the steps, because only it knows which ones it has already counted.
    downloaded: int
    #: What the server said this step weighs, when it said anything at all.
    expected: int | None


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


async def _download(
    client: httpx.AsyncClient,
    params: dict[str, str],
    report: Callable[[int, int | None], None],
) -> bytes:
    """One dump, streamed, with the bytes reported as they land.

    Streamed rather than read whole so there is something to report at all: these
    are tens of megabytes, and a caller waiting on ``response.content`` has
    nothing to say for the minute it takes.
    """
    buffer = bytearray()
    async with client.stream("GET", CARDINFO_URL, params=params) as response:
        response.raise_for_status()
        raw = response.headers.get("content-length")
        expected = int(raw) if raw and raw.isdigit() else None
        report(0, expected)

        # Decoded bytes, not httpx's num_bytes_downloaded. That counts what came
        # off the wire, which is the right pairing for a Content-Length — but
        # YGOPRODeck sends none and gzips the body, so the wire figure is about
        # a seventh of the dump and measuring by it puts the estimate out by the
        # same factor. The decoded length is also what the file on disk weighs,
        # which is the size the UI quotes.
        reported = 0
        async for chunk in response.aiter_bytes():
            buffer += chunk
            if len(buffer) - reported >= _PROGRESS_STEP:
                reported = len(buffer)
                report(reported, expected)
        report(len(buffer), expected)

    return bytes(buffer)


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
    on_progress: Callable[[DumpProgress], None] | None = None,
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
        on_progress: called as the bytes land, and once more when the download
            gives way to deriving the parquet. Optional: the CLI wants none of
            it, and the API's progress endpoint is the only caller that does.
    """
    paths = CachePaths(cache_dir or CACHE_DIR)
    wanted = CATALOGUE_LANGUAGES if languages is None else languages
    existing = load_meta(paths.meta)
    if existing is not None and not force:
        return existing

    # Before the first write, not after: the localized dumps land here too.
    paths.root.mkdir(parents=True, exist_ok=True)

    steps = 1 + len(wanted)

    def reporter(phase: str, step: int, language: str | None = None):
        def report(downloaded: int, expected: int | None) -> None:
            if on_progress is not None:
                on_progress(
                    DumpProgress(
                        phase=phase,
                        language=language,
                        step=step,
                        steps=steps,
                        downloaded=downloaded,
                        expected=expected,
                    )
                )

        return report

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
    localized: dict[str, list[dict]] = {}
    try:
        await shared_limiter().acquire()
        body = await _download(client, _NO_PARAMS, reporter("cards", 1))

        for index, language in enumerate(wanted, start=2):
            try:
                await shared_limiter().acquire()
                content = await _download(
                    client,
                    {"language": language},
                    reporter("names", index, language.upper()),
                )
                cards = _cards_of(content, CARDINFO_URL)
            except Exception:
                # One unavailable translation must not cost the whole refresh.
                log.warning("no %s card names; search falls back to English", language,
                            exc_info=True)
                continue
            localized[language.upper()] = cards
            _write_atomically(paths.localized(language), content)
    finally:
        if owns_client:
            await client.aclose()

    cards = _cards_of(body, CARDINFO_URL)
    _write_atomically(paths.dump, body)

    reporter("building", steps)(0, None)
    # On a thread: this is CPU-bound DuckDB work over some 14,000 cards, and on
    # the event loop it would stall every other request — the progress endpoint
    # being polled about it included — for as long as it runs.
    await asyncio.to_thread(
        normalize_dump,
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
