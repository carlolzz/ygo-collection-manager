"""The FastAPI app.

Local, single-user, read-only. There is no auth: the scanner app owns the
collection, and this only reads its export.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import FRONTEND_DIST, WARM_IMAGES_ON_STARTUP
from ..images import ImageCache
from ..pricing.refine import JobRegistry
from ..pricing.snapshots import SnapshotStore
from .deps import Database
from .routes import cards, catalogue, collection, deck, images, stats, valuation

__all__ = ["app", "create_app"]

log = logging.getLogger(__name__)


def create_app(csv_path: Path | str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # A renamed column fails the app on boot, with the column named. A
        # *missing* export does not: the container starts with an empty mount.
        app.state.db = Database(csv_path)
        app.state.snapshots = SnapshotStore()
        app.state.jobs = JobRegistry()
        app.state.images = ImageCache()

        if WARM_IMAGES_ON_STARTUP and app.state.db.has_collection:
            # Only the cards actually owned — seconds, not a gigabyte of art for
            # cards nobody is looking at. Failures here must not stop the app.
            try:
                result = await app.state.images.warm_owned(app.state.db.cursor())
                log.info("image cache warmed: %s", result)
            except Exception:
                log.warning("image warm-up failed; art will load on demand", exc_info=True)
        try:
            yield
        finally:
            app.state.snapshots.flush()
            app.state.snapshots.close()
            app.state.db.close()

    app = FastAPI(
        title="YGO Collection Explorer",
        description=__doc__,
        version="0.2.0",
        lifespan=lifespan,
    )

    # The Vite dev server runs on a different port during development. In the
    # container the frontend is served from this same origin, so this is unused.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    for router in (
        cards.router,
        stats.router,
        catalogue.router,
        collection.router,
        valuation.router,
        deck.router,
        images.router,
    ):
        app.include_router(router, prefix="/api")

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built SPA, when there is one.

    Absent in development — Vite serves it and proxies /api here — and present
    in the container, where one origin serves both.
    """
    if not FRONTEND_DIST.is_dir():
        return

    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index = FRONTEND_DIST / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """Client-side routing: unknown paths fall through to the SPA."""
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
