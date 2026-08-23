"""Whether an export is loaded, and getting cards into and out of it.

Several ways in — a CSV from the scanner, rows typed by hand, an edit, a
deletion — and one rule covering all of them: **no file already in the data
directory is ever modified**. Every write lands on a *new* timestamped export,
which is then loaded. The previous file is still on disk, so any save is undone
by deleting the newest one.

The upload exists because the Docker image ships with an empty mount, and asking
a non-technical user to drop a file into a bind mount by hand is a worse answer
than a button. An upload onto an existing collection is the interesting case:
replacing is sometimes right and sometimes destroys half the collection, so the
choice is the caller's — ``/preview`` reports how much of the file is already
known, and ``/upload`` takes the decision made from that.

``/entries`` needs no such question. Hand-entered rows are always *additional*,
so they go through the merge in its summing mode and nothing can be lost.
Editing and deleting go through ``revise``, which is the same fold with the old
row taken out first.

``/export`` is the way back out, and the reason it can simply hand over a file
is the rule above: whatever is loaded is already a valid export.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ...collection.entry import write_staged
from ...collection.loader import CollectionError, read_header, row_count
from ...collection.merge import merge_counts, merge_to_csv
from ...collection.revise import KEY_MATCH, key_values, revise_to_csv
from ...collection.schema import COLLECTION_COLUMNS, ISO_FORMAT
from ...config import DATA_DIR
from ..deps import Database, get_db
from ..models import (
    CollectionStatus,
    EntryEdit,
    EntryKey,
    EntryKeys,
    NewEntries,
    UploadPreview,
)

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


def _commit(db: Database, build: Callable[[Path], None], failure: str) -> None:
    """Write a fresh export, load it, and put everything back if either step fails.

    Shared by the two write paths so there is one answer to "what happens when a
    save goes wrong", rather than one per endpoint.
    """
    previous = db.requested
    target = _fresh_target()
    try:
        build(target)
        db.reload(target)
    except Exception as exc:
        # Leaving a bad file behind would break the next startup, which picks the
        # newest CSV in the directory. Unlinked before the handle is put back, so
        # a rollback to auto-discovery cannot re-find it.
        target.unlink(missing_ok=True)
        db.reload(previous)
        raise HTTPException(422, f"{failure} {exc}") from None


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

        def build(target: Path) -> None:
            if existing is not None:
                merge_to_csv(existing, staged, target, sum_quantities=mode == "merge_sum")
            else:
                target.write_bytes(body)

        _commit(db, build, "That CSV could not be loaded.")

    return _status(db)


@router.post("/entries", response_model=CollectionStatus)
def add_entries(
    db: Annotated[Database, Depends(get_db)],
    payload: NewEntries,
) -> CollectionStatus:
    """Add hand-entered rows to the collection.

    An add is a merge: the rows are staged as an export and folded into the
    loaded one with quantities summed. So a row matching a printing, grade,
    edition and language already owned increments that row rather than
    duplicating it, and the caller does not have to know which case it is in.

    Every copy in the payload carries its own details, which is how three copies
    of one card in three languages are entered in a single request.
    """
    existing = db.csv_path if db.has_collection else None
    rows = [row.model_dump() for row in payload.rows]

    # Staged outside the data directory, for the reason _staged gives: a file
    # named like an export that fails to load must not be found on next boot.
    with tempfile.TemporaryDirectory(prefix="ygo-entries-") as tmp:
        staged = Path(tmp) / "entries.csv"
        write_staged(rows, staged)

        def build(target: Path) -> None:
            if existing is not None:
                merge_to_csv(existing, staged, target, sum_quantities=True)
            else:
                # The first card of a collection that has no export yet.
                shutil.copyfile(staged, target)

        _commit(db, build, "Those cards could not be saved.")

    return _status(db)


#: The row's acquisition date, which is also the existence check. Selected
#: through strftime so it comes back in the shape the export contract writes,
#: ready to hand to write_staged unchanged.
_CREATED_AT = (
    f"SELECT strftime(created_at AT TIME ZONE 'UTC', '{ISO_FORMAT}') "
    f"FROM collection WHERE {KEY_MATCH}"
)


def _loaded_csv(db: Database) -> Path:
    if not db.has_collection or db.csv_path is None:
        raise HTTPException(404, "No collection is loaded, so there is nothing to change.")
    return db.csv_path


def _created_at(db: Database, key: EntryKey) -> str:
    """When the row was acquired, or 404 if there is no such row.

    Checked against the *loaded* table before anything is written, so a key from
    a page left open in another tab costs a query and leaves no file behind.
    """
    found = db.cursor().execute(_CREATED_AT, key_values(key.model_dump())).fetchone()
    if found is None:
        raise HTTPException(
            404,
            "That row is no longer in the collection — it may have been changed "
            "somewhere else. Reload the page and try again.",
        )
    return found[0]


@router.patch("/entries", response_model=CollectionStatus)
def edit_entry(
    db: Annotated[Database, Depends(get_db)],
    payload: EntryEdit,
) -> CollectionStatus:
    """Change one row: the old one is removed and the new one folded back in.

    Which is the scanner's own semantic, and has two consequences worth naming.
    Editing a row into a printing, grade, edition and language already owned
    *merges* into that row rather than creating a second one of the same thing.
    And setting the quantity sets it — the old row is gone before the fold
    happens, so two copies edited to five are five, not seven.

    The acquisition date is carried over from the row being replaced, so
    correcting a condition does not rewrite when the card was owned since.

    Two clients editing different rows at once is last-write-wins over the whole
    file, which is inherent to storing the collection as one CSV and is not worth
    locking against in a single-user app.
    """
    existing = _loaded_csv(db)
    created_at = _created_at(db, payload.key)
    key = payload.key.model_dump()
    row = {**payload.row.model_dump(), "created_at": created_at}

    # Staged outside the data directory, for the reason _staged gives.
    with tempfile.TemporaryDirectory(prefix="ygo-edit-") as tmp:
        staged = Path(tmp) / "edit.csv"
        write_staged([row], staged)
        _commit(
            db,
            lambda target: revise_to_csv(existing, target, drop_keys=[key], incoming=staged),
            "That change could not be saved.",
        )

    return _status(db)


@router.delete("/entries", response_model=CollectionStatus)
def delete_entries(
    db: Annotated[Database, Depends(get_db)],
    payload: EntryKeys,
) -> CollectionStatus:
    """Remove rows from the collection.

    Every key is checked first and one miss refuses the whole request, for the
    reason a partly-applied save is refused: the caller cannot tell which half
    went through. Nothing is destroyed either way — the export the rows are still
    in stays on disk, and deleting the file this writes brings them back.
    """
    existing = _loaded_csv(db)
    for key in payload.keys:
        _created_at(db, key)
    keys = [key.model_dump() for key in payload.keys]

    _commit(
        db,
        lambda target: revise_to_csv(existing, target, drop_keys=keys),
        "Those rows could not be removed.",
    )
    return _status(db)


@router.get("/export")
def export_collection(db: Annotated[Database, Depends(get_db)]) -> FileResponse:
    """Download the loaded export, byte for byte.

    Not regenerated: what is loaded is already a CSV in the export contract,
    either the scanner's own or one this app wrote through the same projection
    every other write uses. So the file that comes down re-uploads cleanly, and
    "the CSV is the storage" is a claim the user can check.

    Mostly here for the container, where the data directory is a volume that a
    non-technical user has no easy way to reach.
    """
    path = db.csv_path
    # The documented undo is "delete the newest file", so the loaded path can
    # point at something that has since been removed. Caught here rather than
    # halfway through a response whose headers have already gone out.
    if not db.has_collection or path is None or not path.is_file():
        raise HTTPException(404, "No collection is loaded, so there is nothing to export.")
    return FileResponse(path, media_type="text/csv", filename=path.name)
