"""Whether an export is loaded, and getting one in.

The CSV remains read-only input: the upload below writes a **new** timestamped
file into the data directory and never modifies an existing one. It exists
because the Docker image ships with an empty mount, and asking a non-technical
user to drop a file into a bind mount by hand is a worse answer than a button.

An upload onto an existing collection is the interesting case. Replacing is
sometimes right and sometimes destroys half the collection, so the choice is
the caller's: ``/preview`` reports how much of the file is already known, and
``/upload`` takes the decision made from that.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ...collection.loader import CollectionError, read_header, row_count
from ...collection.merge import merge_counts, merge_to_csv
from ...collection.schema import COLLECTION_COLUMNS
from ...config import DATA_DIR
from ..deps import Database, get_db
from ..models import CollectionStatus, UploadPreview

router = APIRouter(prefix="/collection", tags=["collection"])

MAX_UPLOAD_BYTES = 32 * 1024 * 1024

#: What to do with rows the loaded collection already has.
MERGE_MODES = ("replace", "merge_sum", "merge_keep")


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


async def _body(file: UploadFile) -> bytes:
    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That file is larger than 32 MB — is it a collection export?")
    if not body.strip():
        raise HTTPException(422, "The uploaded file is empty.")
    return body


@contextmanager
def _staged(body: bytes) -> Iterator[Path]:
    """Put the bytes somewhere DuckDB can read them, and check they are an export.

    Deliberately *not* in the data directory: a file named like an export that
    turns out not to be one, or one left behind by a crash mid-request, would be
    picked up as the collection on the next boot.
    """
    with tempfile.TemporaryDirectory(prefix="ygo-upload-") as tmp:
        staged = Path(tmp) / "upload.csv"
        staged.write_bytes(body)
        try:
            header = read_header(staged)
        except Exception as exc:
            raise HTTPException(422, f"That file is not a CSV. {exc}") from None
        if header != COLLECTION_COLUMNS:
            raise HTTPException(
                422,
                "That CSV is not a collection export. Expected the twelve export "
                f"columns {list(COLLECTION_COLUMNS)}, got {list(header)}.",
            )
        yield staged


def _fresh_target() -> Path:
    """A collection path in the data directory that no file occupies yet.

    The stamp alone is only accurate to the second, so two uploads inside the
    same second would land on one path — the second overwriting the first, and
    the rollback deleting it outright. The suffix sorts after the bare name,
    which matters because startup picks the lexicographically last CSV.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    target = DATA_DIR / f"ygo_collection_{stamp}.csv"
    for n in range(1, 100):
        if not target.exists():
            return target
        target = DATA_DIR / f"ygo_collection_{stamp}_{n:02d}.csv"
    raise HTTPException(429, "Too many uploads in the same second. Try again.")


@router.post("/preview", response_model=UploadPreview)
async def preview_collection(
    db: Annotated[Database, Depends(get_db)],
    file: Annotated[UploadFile, File(description="A CSV exported from the scanner app")],
) -> UploadPreview:
    """Report how an export would land on the loaded collection, changing nothing.

    Answered without keeping the file: the browser sends it again with the
    decision, which costs one extra request on a file measured in kilobytes and
    saves holding — and expiring — server-side upload state.
    """
    body = await _body(file)
    with _staged(body) as staged:
        if not db.has_collection or db.csv_path is None:
            rows = row_count(staged)
            return UploadPreview(
                has_collection=False,
                current_rows=0,
                incoming_rows=rows,
                overlapping_rows=0,
                new_rows=rows,
            )
        try:
            counts = merge_counts(db.csv_path, staged)
        except CollectionError as exc:
            raise HTTPException(422, f"That CSV is not a collection export. {exc}") from None
    return UploadPreview(
        has_collection=True,
        current_rows=_status(db).collection_rows,
        incoming_rows=counts.incoming_rows,
        overlapping_rows=counts.overlapping_rows,
        new_rows=counts.new_rows,
    )


@router.post("/upload", response_model=CollectionStatus)
async def upload_collection(
    db: Annotated[Database, Depends(get_db)],
    file: Annotated[UploadFile, File(description="A CSV exported from the scanner app")],
    mode: Annotated[str, Form(description="One of replace, merge_sum, merge_keep")] = "replace",
) -> CollectionStatus:
    """Accept an export and load it.

    Written under a fresh timestamped name, so an upload can never overwrite an
    export already sitting in the data directory. ``replace`` stores the
    uploaded bytes verbatim; the merge modes store the combined result, leaving
    both inputs on disk untouched.
    """
    if mode not in MERGE_MODES:
        raise HTTPException(422, f"Unknown mode {mode!r}; expected one of {list(MERGE_MODES)}.")
    body = await _body(file)

    with _staged(body) as staged:
        # Nothing to merge with. Asking the caller to retry would be pedantic:
        # every mode means the same thing against an empty collection.
        existing = db.csv_path if (mode != "replace" and db.has_collection) else None
        previous = db.requested

        target = _fresh_target()
        try:
            if existing is not None:
                merge_to_csv(existing, staged, target, sum_quantities=mode == "merge_sum")
            else:
                target.write_bytes(body)
            db.reload(target)
        except Exception as exc:
            # Leaving a bad file behind would break the next startup, which
            # picks the newest CSV in the directory. Unlinked before the handle
            # is put back, so a rollback to auto-discovery cannot re-find it.
            target.unlink(missing_ok=True)
            db.reload(previous)
            raise HTTPException(422, f"That CSV could not be loaded. {exc}") from None

    return _status(db)
