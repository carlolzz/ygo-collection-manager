"""The local card-art cache.

YGOPRODeck's guide is explicit: do not hotlink, download each image once and
re-host it, or the IP gets blacklisted. So the browser never sees an upstream
URL — the API exposes ``source_image_url`` purely so this module knows what to
fetch, and every ``<img>`` points at ``/api/images/{passcode}``.

Owned cards are warmed at startup; anything else — an alternate artwork, a card
a deck needs but the collection lacks — is fetched on first view. Bulk-fetching
all ~14.5k images would be a gigabyte-plus of art for cards nobody is looking
at.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import duckdb
import httpx

from .config import CACHE_DIR
from .net.limiter import shared_limiter

__all__ = ["ImageCache", "PLACEHOLDER_BYTES"]

_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
WARM_CONCURRENCY = 4

# A neutral card back stands in for art that 404s, so a missing image is a card
# with no picture rather than a broken layout.
PLACEHOLDER_BYTES = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 421 614">'
    b'<rect width="421" height="614" rx="18" fill="#2b2b33"/>'
    b'<rect x="14" y="14" width="393" height="586" rx="10" fill="none" '
    b'stroke="#4a4a57" stroke-width="3"/>'
    b'<text x="210" y="300" text-anchor="middle" font-family="system-ui,sans-serif" '
    b'font-size="26" fill="#7c7c8a">no artwork</text>'
    b'<text x="210" y="336" text-anchor="middle" font-family="system-ui,sans-serif" '
    b'font-size="18" fill="#5c5c69">cached locally</text></svg>'
)


class ImageCache:
    """Art on disk, keyed by passcode."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else CACHE_DIR / "images"
        self.root.mkdir(parents=True, exist_ok=True)
        # Passcodes already known to have no art upstream, so a repeated view
        # does not repeat the request.
        self._missing: set[str] = set()

    def path_for(self, passcode: str) -> Path:
        # Passcodes are digits, but never trust them into a path.
        safe = "".join(ch for ch in passcode if ch.isalnum())
        return self.root / f"{safe}.jpg"

    def cached(self, passcode: str) -> Path | None:
        path = self.path_for(passcode)
        return path if path.is_file() else None

    def known_missing(self, passcode: str) -> bool:
        return passcode in self._missing

    async def fetch(
        self, passcode: str, url: str, *, client: httpx.AsyncClient | None = None
    ) -> Path | None:
        """Download once. Returns None when the art genuinely is not there."""
        existing = self.cached(passcode)
        if existing is not None:
            return existing
        if passcode in self._missing:
            return None

        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
        try:
            await shared_limiter().acquire()
            response = await client.get(url)
            if response.status_code == 404:
                self._missing.add(passcode)
                return None
            response.raise_for_status()
            body = response.content
        except httpx.HTTPError:
            # Not cached as missing: a transient failure should be retryable on
            # the next view, unlike a genuine 404.
            return None
        finally:
            if owns_client:
                await client.aclose()

        target = self.path_for(passcode)
        tmp = target.with_suffix(".part")
        tmp.write_bytes(body)
        tmp.replace(target)
        return target

    async def warm_owned(
        self, con: duckdb.DuckDBPyConnection, *, client: httpx.AsyncClient | None = None
    ) -> dict[str, int]:
        """Fetch art for every owned card. Resumable: cached files are skipped."""
        rows = con.execute(
            "SELECT DISTINCT passcode, image_url FROM collection_enriched "
            "WHERE image_url IS NOT NULL"
        ).fetchall()
        pending = [(p, u) for p, u in rows if self.cached(p) is None]
        if not pending:
            return {"fetched": 0, "cached": len(rows), "failed": 0}

        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
        semaphore = asyncio.Semaphore(WARM_CONCURRENCY)
        results: list[Path | None] = []

        async def one(passcode: str, url: str) -> None:
            async with semaphore:
                results.append(await self.fetch(passcode, url, client=client))

        try:
            await asyncio.gather(*(one(p, u) for p, u in pending))
        finally:
            if owns_client:
                await client.aclose()

        fetched = sum(1 for r in results if r is not None)
        return {
            "fetched": fetched,
            "cached": len(rows) - len(pending),
            "failed": len(pending) - fetched,
        }
