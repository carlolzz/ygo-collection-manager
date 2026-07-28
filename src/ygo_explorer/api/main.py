"""The FastAPI app.

Local, single-user, read-only. There is no auth and no write path: the scanner
app owns the collection, and this only ever reads its export.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .deps import Database
from .routes import cards, catalogue, stats

__all__ = ["app", "create_app"]


def create_app(csv_path: Path | str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Loading at startup means a renamed column fails the app on boot, with
        # the column named, rather than on some later request.
        app.state.db = Database(csv_path)
        try:
            yield
        finally:
            app.state.db.close()

    app = FastAPI(
        title="YGO Collection Explorer",
        description=__doc__,
        version="0.1.0",
        lifespan=lifespan,
    )

    # The Vite dev server runs on a different port during development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(cards.router, prefix="/api")
    app.include_router(stats.router, prefix="/api")
    app.include_router(catalogue.router, prefix="/api")

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
