"""Serving card art from the local cache — never hotlinked from YGOPRODeck."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse

from ...images import PLACEHOLDER_BYTES, ImageCache
from ..deps import Database, get_db

router = APIRouter(prefix="/images", tags=["images"])


def get_images(request: Request) -> ImageCache:
    return request.app.state.images


def _placeholder() -> Response:
    return Response(
        content=PLACEHOLDER_BYTES,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/{passcode}")
async def card_image(
    passcode: str,
    db: Annotated[Database, Depends(get_db)],
    images: Annotated[ImageCache, Depends(get_images)],
):
    """Serve one card's art, downloading it once if this is the first view.

    The lazy fetch is what keeps the cache to the cards actually looked at. It
    is a single rate-limited request, and only ever on a cache miss.
    """
    cached = images.cached(passcode)
    if cached is None and not images.known_missing(passcode):
        row = db.cursor().execute(
            "SELECT image_url FROM cards WHERE passcode = ? AND image_url IS NOT NULL",
            [passcode],
        ).fetchone()
        if row:
            cached = await images.fetch(passcode, row[0])

    if cached is None:
        return _placeholder()

    return FileResponse(
        cached,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800"},
    )
