"""The FastAPI app.

Local and single-user. There is no auth. The scanner app owns the collection;
this reads its export and writes new ones only when asked to (an upload, an
added or edited row). The one thing it keeps of its own is the saved deck
checks, in their own file beside the export.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..catalogue.job import RefreshRegistry
from ..config import FRONTEND_DIST, WARM_IMAGES_ON_STARTUP
from ..deck.history import DeckCheckStore
from ..images import ImageCache
from ..pricing.refine import JobRegistry
from ..pricing.snapshots import SnapshotStore
from .deps import Database
from .routes import cards, catalogue, collection, deck, images, stats, valuation

__all__ = ["app", "create_app"]

log = logging.getLogger(__name__)


def _version() -> str:
    """The installed distribution's version, so this cannot drift from pyproject.

    It did: the number here read 0.5.0 while the project was on 0.6.0. Falls back
    only when the package is not installed at all, which is a source checkout
    being imported directly rather than anything a user will see.
    """
    try:
        return package_version("ygo-collection-manager")
    except PackageNotFoundError:
        return "0+unknown"


def create_app(csv_path: Path | str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # A renamed column fails the app on boot, with the column named. A
        # *missing* export does not: the container starts with an empty mount.
        app.state.db = Database(csv_path)
        app.state.snapshots = SnapshotStore()
        # Written through on every change, so it needs no flush on the way out.
        app.state.deck_checks = DeckCheckStore()
        app.state.jobs = JobRegistry()
        app.state.catalogue_jobs = RefreshRegistry()
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
        title="YGO Collection Manager",
        description=__doc__,
        version=_version(),
        lifespan=lifespan,
    )

    # The Vite dev server runs on a different port during development. In the
    # container the frontend is served from this same origin, so this is unused.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
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

    # Handled on the 404 rather than as a catch-all route. A catch-all GET
    # matches before Starlette can report a method mismatch, so a GET on a
    # POST-only endpoint would answer 200 with index.html instead of 405 —
    # every API mistake silently becoming a valid-looking page.
    @app.exception_handler(404)
    async def spa_fallback(request: Request, exc: HTTPException):
        path = request.url.path
        if path.startswith("/api/"):
            return JSONResponse({"detail": exc.detail}, status_code=404)
        candidate = FRONTEND_DIST / path.lstrip("/")
        if candidate.is_file() and candidate.resolve().is_relative_to(FRONTEND_DIST):
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
