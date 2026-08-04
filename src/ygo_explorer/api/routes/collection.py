"""Whether an export is loaded, and getting one in.

The CSV remains read-only input: the upload below writes a **new** timestamped
file into the data directory and never modifies an existing one. It exists
because the Docker image ships with an empty mount, and asking a non-technical
user to drop a file into a bind mount by hand is a worse answer than a button.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ...collection.loader import CollectionError, read_header
from ...collection.schema import COLLECTION_COLUMNS
from ...config import DATA_DIR
from ..deps import Database, get_db
from ..models import CollectionStatus

router = APIRouter(prefix="/collection", tags=["collection"])

MAX_UPLOAD_BYTES = 32 * 1024 * 1024


def _status(db: Database) -> CollectionStatus:
    rows = 0
    if db.has_collection:
        rows = db.cursor().execute("SELECT COUNT(*) FROM collection").fetchone()[0]
    return CollectionStatus(
        has_collection=db.has_collection,
        csv_path=str(db.csv_path) if db.csv_path else None,
        collection_rows=rows,
        message=db.message,
    )


@router.get("/status", response_model=CollectionStatus)
def collection_status(db: Annotated[Database, Depends(get_db)]) -> CollectionStatus:
    """Whether a collection is loaded. The app runs, emptily, without one."""
    return _status(db)


@router.post("/upload", response_model=CollectionStatus)
async def upload_collection(
    db: Annotated[Database, Depends(get_db)],
    file: Annotated[UploadFile, File(description="A CSV exported from the scanner app")],
) -> CollectionStatus:
    """Accept an export and load it.

    Written under a fresh timestamped name, so an upload can never overwrite an
    export already sitting in the data directory.
    """
    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That file is larger than 32 MB — is it a collection export?")
    if not body.strip():
        raise HTTPException(422, "The uploaded file is empty.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # The stamp alone is only accurate to the second, so two uploads inside the
    # same second would land on one path — the second overwriting the first, and
    # the rollback below deleting it outright. The suffix sorts after the bare
    # name, which matters because startup picks the lexicographically last CSV.
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    target = DATA_DIR / f"ygo_collection_{stamp}.csv"
    for n in range(1, 100):
        if not target.exists():
            break
        target = DATA_DIR / f"ygo_collection_{stamp}_{n:02d}.csv"
    else:
        raise HTTPException(429, "Too many uploads in the same second. Try again.")
    target.write_bytes(body)

    # Validate before adopting it, and clean up if it is not an export at all —
    # leaving a bad file behind would break the next startup, which picks the
    # newest CSV in the directory.
    try:
        header = read_header(target)
        if header != COLLECTION_COLUMNS:
            raise CollectionError(
                f"Expected the twelve export columns {list(COLLECTION_COLUMNS)}, "
                f"got {list(header)}."
            )
        db.reload(target)
    except Exception as exc:
        target.unlink(missing_ok=True)
        db.reload()
        raise HTTPException(422, f"That CSV is not a collection export. {exc}") from None

    return _status(db)
