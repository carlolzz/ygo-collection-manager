"""Combining an uploaded export with the loaded one.

The costly mistake this guards against is arithmetic: uploading a full export
twice must not double a collection, and choosing to add quantities must
actually add them. Both directions are asserted on real numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ygo_explorer.api.main import create_app
from ygo_explorer.catalogue.normalize import normalize_dump
from ygo_explorer.collection.loader import open_collection
from ygo_explorer.collection.merge import merge_counts, merge_to_csv
from ygo_explorer.collection.schema import COLLECTION_COLUMNS

HEADER = ",".join(COLLECTION_COLUMNS)


def _row(
    passcode: str = "46986414",
    name: str = "Dark Magician",
    set_code: str = "SDY-006",
    set_name: str = "Starter Deck: Yugi",
    rarity: str = "Ultra Rare",
    condition: str = "NEAR_MINT",
    edition: str = "FIRST",
    language: str = "EN",
    quantity: int = 1,
    notes: str = "",
    created_at: str = "2026-01-01T00:00:00Z",
    updated_at: str = "2026-01-01T00:00:00Z",
) -> str:
    return ",".join(
        [
            passcode, name, set_code, set_name, rarity, condition, edition,
            language, str(quantity), notes, created_at, updated_at,
        ]
    )


def _csv(tmp_path: Path, name: str, *rows: str) -> Path:
    path = tmp_path / name
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return path


def _merged(tmp_path: Path, old: Path, new: Path, *, sum_quantities: bool) -> list[tuple]:
    """Merge, then read the result back through the ordinary loader."""
    out = tmp_path / "merged.csv"
    merge_to_csv(old, new, out, sum_quantities=sum_quantities)
    with open_collection(out) as con:
        return con.execute(
            "SELECT passcode, name, set_code, condition, language, quantity, notes "
            "FROM collection ORDER BY name, language, condition"
        ).fetchall()


# --- counts ------------------------------------------------------------------


def test_an_export_uploaded_onto_itself_is_entirely_overlap(fixture_csv):
    counts = merge_counts(fixture_csv, fixture_csv)
    assert (counts.incoming_rows, counts.overlapping_rows, counts.new_rows) == (8, 8, 0)


def test_counts_split_the_known_from_the_new(tmp_path):
    old = _csv(tmp_path, "old.csv", _row(), _row(language="DE"))
    new = _csv(tmp_path, "new.csv", _row(), _row(language="IT"), _row(passcode="55144522"))
    counts = merge_counts(old, new)
    assert (counts.incoming_rows, counts.overlapping_rows, counts.new_rows) == (3, 1, 2)


# --- quantities --------------------------------------------------------------


def test_summing_adds_the_quantities(tmp_path):
    old = _csv(tmp_path, "old.csv", _row(quantity=1))
    new = _csv(tmp_path, "new.csv", _row(quantity=1))
    assert [(r[0], r[5]) for r in _merged(tmp_path, old, new, sum_quantities=True)] == [
        ("46986414", 2)
    ]


def test_keeping_collapses_duplicates_to_one(tmp_path):
    old = _csv(tmp_path, "old.csv", _row(quantity=1))
    new = _csv(tmp_path, "new.csv", _row(quantity=1))
    assert [(r[0], r[5]) for r in _merged(tmp_path, old, new, sum_quantities=False)] == [
        ("46986414", 1)
    ]


@pytest.mark.parametrize(("held", "uploaded"), [(3, 5), (5, 3)])
def test_without_summing_the_uploaded_quantity_wins(tmp_path, held, uploaded):
    """Including when it is lower — that is how selling two copies is recorded."""
    old = _csv(tmp_path, "old.csv", _row(quantity=held))
    new = _csv(tmp_path, "new.csv", _row(quantity=uploaded))
    assert _merged(tmp_path, old, new, sum_quantities=False)[0][5] == uploaded


def test_a_row_only_the_collection_has_survives_either_way(tmp_path):
    old = _csv(tmp_path, "old.csv", _row(quantity=4, passcode="55144522", name="Pot of Greed"))
    new = _csv(tmp_path, "new.csv", _row(quantity=1))
    for summing in (True, False):
        rows = _merged(tmp_path, old, new, sum_quantities=summing)
        assert [(r[0], r[5]) for r in rows] == [("46986414", 1), ("55144522", 4)]


# --- the natural key ---------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("language", "DE"),
        ("condition", "POOR"),
        ("edition", "UNLIMITED"),
        ("set_code", "LOB-001"),
        ("rarity", "Common"),
    ],
)
def test_rows_differing_in_any_key_column_stay_apart(tmp_path, field, value):
    old = _csv(tmp_path, "old.csv", _row())
    new = _csv(tmp_path, "new.csv", _row(**{field: value}))
    assert len(_merged(tmp_path, old, new, sum_quantities=True)) == 2


def test_rows_with_no_printing_recorded_still_merge(tmp_path):
    """The nullable key columns are NULL on both sides, and NULL != NULL in SQL.

    Grouping is what makes this work; an equijoin would have dropped the row
    and quietly added a duplicate instead.
    """
    blank = _row(set_code="", set_name="", rarity="", quantity=2)
    old = _csv(tmp_path, "old.csv", blank)
    new = _csv(tmp_path, "new.csv", blank)
    rows = _merged(tmp_path, old, new, sum_quantities=True)
    assert len(rows) == 1
    assert rows[0][2] is None and rows[0][5] == 4


def test_a_row_differing_only_in_notes_is_the_same_row(tmp_path):
    """Notes are not identity — the same card annotated twice is one card."""
    old = _csv(tmp_path, "old.csv", _row(notes="from a trade"))
    new = _csv(tmp_path, "new.csv", _row(notes="mint sleeve"))
    rows = _merged(tmp_path, old, new, sum_quantities=False)
    assert len(rows) == 1
    assert rows[0][6] == "mint sleeve"  # the uploaded file is the newer statement


# --- what the merged file is -------------------------------------------------


def test_the_merged_file_is_an_export_like_any_other(tmp_path, fixture_csv):
    """Round-tripped through the loader, with every awkward value intact."""
    out = tmp_path / "merged.csv"
    merge_to_csv(fixture_csv, fixture_csv, out, sum_quantities=False)

    assert out.read_text(encoding="utf-8").splitlines()[0] == HEADER

    with open_collection(out) as con:
        rows = con.execute(
            "SELECT passcode, name, notes FROM collection ORDER BY passcode"
        ).fetchall()

    # Leading zeros are real, so the widths must survive the write.
    assert [r[0] for r in rows[:3]] == ["00000001", "00004041", "27204311"]
    # The apostrophe guard was stripped on read and put back on write, so the
    # loader strips it again and the name is the name.
    assert rows[0][1] == "=Test Formula Card"
    assert rows[0][2] == "-30% off"
    # Embedded double quotes survive the CSV dialect round trip.
    assert rows[2][1] == 'Nibiru, the "Primal" Being'


def test_merging_reads_both_files_and_writes_neither(tmp_path, fixture_csv):
    old = _csv(tmp_path, "old.csv", _row())
    before = (old.read_bytes(), fixture_csv.read_bytes())
    merge_to_csv(old, fixture_csv, tmp_path / "merged.csv", sum_quantities=True)
    assert (old.read_bytes(), fixture_csv.read_bytes()) == before


def test_a_file_that_is_not_an_export_is_refused_before_anything_is_written(tmp_path):
    from ygo_explorer.collection.loader import CollectionSchemaError

    old = _csv(tmp_path, "old.csv", _row())
    junk = tmp_path / "junk.csv"
    junk.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    out = tmp_path / "merged.csv"

    with pytest.raises(CollectionSchemaError):
        merge_to_csv(old, junk, out, sum_quantities=True)
    assert not out.exists()


# --- through the API ---------------------------------------------------------


@pytest.fixture
def client(fixture_csv: Path, fixture_dump: Path, tmp_path: Path, monkeypatch):
    """A loaded collection, with uploads landing in a throwaway data directory."""
    cards = json.loads(fixture_dump.read_text(encoding="utf-8"))["data"]
    paths = {
        "CARDS_PARQUET": tmp_path / "cards.parquet",
        "CARD_SETS_PARQUET": tmp_path / "card_sets.parquet",
        "CARD_PRICES_PARQUET": tmp_path / "card_prices.parquet",
    }
    normalize_dump(
        cards,
        cards_path=paths["CARDS_PARQUET"],
        card_sets_path=paths["CARD_SETS_PARQUET"],
        card_prices_path=paths["CARD_PRICES_PARQUET"],
    )
    for name, path in paths.items():
        monkeypatch.setattr(f"ygo_explorer.catalogue.views.{name}", path)
    monkeypatch.setattr("ygo_explorer.api.routes.collection.DATA_DIR", tmp_path / "data")
    with TestClient(create_app(fixture_csv)) as c:
        yield c


def _upload(client: TestClient, csv_path: Path, mode: str):
    return client.post(
        "/api/collection/upload",
        files={"file": ("export.csv", csv_path.read_bytes(), "text/csv")},
        data={"mode": mode},
    )


def test_preview_reports_the_overlap_without_loading_anything(client, fixture_csv):
    body = client.post(
        "/api/collection/preview",
        files={"file": ("export.csv", fixture_csv.read_bytes(), "text/csv")},
    ).json()
    assert body == {
        "has_collection": True,
        "current_rows": 8,
        "incoming_rows": 8,
        "overlapping_rows": 8,
        "new_rows": 0,
    }
    # Nothing moved: the collection is still the file it started on.
    assert client.get("/api/collection/status").json()["csv_path"] == str(fixture_csv)


def test_uploading_the_same_export_twice_does_not_double_the_collection(client, fixture_csv):
    before = client.get("/api/cards").json()["total_copies"]
    assert _upload(client, fixture_csv, "merge_keep").status_code == 200
    body = client.get("/api/cards").json()
    assert body["total_copies"] == before
    assert body["total_cards"] == 7


def test_choosing_to_sum_doubles_it(client, fixture_csv):
    before = client.get("/api/cards").json()["total_copies"]
    assert _upload(client, fixture_csv, "merge_sum").status_code == 200
    assert client.get("/api/cards").json()["total_copies"] == before * 2


def test_replace_still_replaces(client, fixture_csv, tmp_path):
    one = _csv(tmp_path, "one.csv", _row(quantity=3))
    assert _upload(client, one, "replace").status_code == 200
    body = client.get("/api/cards").json()
    assert (body["total_cards"], body["total_copies"]) == (1, 3)


def test_merging_adds_the_rows_the_collection_did_not_have(client, tmp_path):
    extra = _csv(tmp_path, "extra.csv", _row(passcode="55144522", name="Pot of Greed", quantity=2))
    assert _upload(client, extra, "merge_keep").status_code == 200
    body = client.get("/api/cards").json()
    assert body["total_cards"] == 8  # the fixture's seven, plus this one


def test_an_unknown_mode_is_refused(client, fixture_csv):
    response = _upload(client, fixture_csv, "obliterate")
    assert response.status_code == 422
    assert client.get("/api/cards").json()["total_cards"] == 7


def test_a_merge_leaves_the_previous_export_on_disk(client, fixture_csv, tmp_path):
    before = fixture_csv.read_bytes()
    assert _upload(client, fixture_csv, "merge_sum").status_code == 200
    loaded = Path(client.get("/api/collection/status").json()["csv_path"])
    assert loaded != fixture_csv
    assert fixture_csv.read_bytes() == before


def test_preview_of_the_first_export_asks_nothing(fixture_csv, tmp_path):
    """With nothing loaded there is no decision to make, so every row is new."""
    with TestClient(create_app(tmp_path / "no-such-export.csv")) as empty:
        body = empty.post(
            "/api/collection/preview",
            files={"file": ("export.csv", fixture_csv.read_bytes(), "text/csv")},
        ).json()
    assert body["has_collection"] is False
    assert (body["incoming_rows"], body["overlapping_rows"], body["new_rows"]) == (8, 0, 8)


def test_a_merge_that_fails_to_load_leaves_the_collection_where_it_was(client, tmp_path):
    """The header is fine, so the failure comes from the data — after the
    handle has already been pointed at the new file. It must be pointed back."""
    loaded = client.get("/api/collection/status").json()["csv_path"]
    broken = _csv(tmp_path, "broken.csv", _row(quantity=0))

    assert _upload(client, broken, "merge_sum").status_code == 422

    status = client.get("/api/collection/status").json()
    assert status["csv_path"] == loaded
    assert client.get("/api/cards").json()["total_cards"] == 7
    # And no half-adopted file is left to be picked up on the next boot.
    assert list((tmp_path / "data").glob("ygo_collection_*.csv")) == []
