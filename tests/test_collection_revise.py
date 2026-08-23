"""Changing and removing rows that are already owned, and getting the CSV out.

The claim under test is that an edit is a removal followed by an add, and that
this is the *right* way round: setting a quantity sets it rather than adding to
it, editing a row onto a combination already owned merges the two, and every one
of these writes leaves the export it revised sitting on disk untouched.

The other half is the natural key. Three of its seven columns are nullable, and
a row with no printing recorded is an ordinary row — so addressing one must not
depend on NULL equalling NULL.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import build_catalogue, patch_catalogue_paths
from ygo_explorer.api.main import create_app
from ygo_explorer.collection.entry import write_staged
from ygo_explorer.collection.loader import open_collection
from ygo_explorer.collection.revise import revise_to_csv
from ygo_explorer.collection.schema import COLLECTION_COLUMNS


# --- fixtures, mirroring test_collection_entries.py --------------------------


@pytest.fixture
def client(fixture_csv: Path, fixture_dump: Path, tmp_path: Path, monkeypatch):
    """A loaded collection, with saves landing in a throwaway data directory."""
    patch_catalogue_paths(monkeypatch, build_catalogue(fixture_dump, tmp_path))
    monkeypatch.setattr("ygo_explorer.api.routes.collection.DATA_DIR", tmp_path / "data")
    with TestClient(create_app(fixture_csv)) as c:
        yield c


@pytest.fixture
def empty_client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("ygo_explorer.api.routes.collection.DATA_DIR", tmp_path / "data")
    with TestClient(create_app(tmp_path / "no-such-export.csv")) as c:
        yield c


#: The Dark Magician row with no printing recorded. Four copies, NULL set.
NO_PRINTING = {
    "passcode": "46986414",
    "set_code": None,
    "set_name": None,
    "rarity": None,
    "condition": "NEAR_MINT",
    "edition": "UNLIMITED",
    "language": "EN",
}

#: Its printed sibling, so the two can be told apart.
PRINTED = {
    "passcode": "46986414",
    "set_code": "SDY-006",
    "set_name": "Starter Deck: Yugi",
    "rarity": "Ultra Rare",
    "condition": "POOR",
    "edition": "FIRST",
    "language": "DE",
}


def _replacement(key: dict, **overrides) -> dict:
    """The ten writable columns of a row, starting from what the key says."""
    row = {**key, "name": "Dark Magician", "quantity": 1, "notes": None}
    row.update(overrides)
    return row


def _edit(client: TestClient, key: dict, **overrides):
    return client.patch(
        "/api/collection/entries",
        json={"key": key, "row": _replacement(key, **overrides)},
    )


def _delete(client: TestClient, *keys: dict):
    # httpx's .delete() refuses a json= kwarg; the request has a body regardless.
    return client.request("DELETE", "/api/collection/entries", json={"keys": list(keys)})


def _owned(client: TestClient, passcode: str) -> list[dict]:
    return client.get(f"/api/cards/{passcode}").json()["rows"]


def _rows(path: Path) -> list[tuple]:
    with open_collection(path) as con:
        return con.execute(
            "SELECT passcode, set_code, condition, edition, language, quantity, name, notes "
            "FROM collection ORDER BY passcode, set_code, condition, edition, language"
        ).fetchall()


def _newest(tmp_path: Path) -> Path:
    return sorted((tmp_path / "data").glob("ygo_collection_*.csv"))[-1]


# --- the writer, on its own --------------------------------------------------


def test_dropping_a_row_leaves_every_other_row_alone(fixture_csv, tmp_path):
    out = tmp_path / "out.csv"
    revise_to_csv(fixture_csv, out, drop_keys=[PRINTED])

    before = [r for r in _rows(fixture_csv) if not (r[0] == "46986414" and r[1] == "SDY-006")]
    assert _rows(out) == before
    assert len(_rows(out)) == 7


def test_a_row_with_no_printing_recorded_is_droppable(fixture_csv, tmp_path):
    """The NULL-safe claim. An equality join would match this key to nothing."""
    out = tmp_path / "out.csv"
    revise_to_csv(fixture_csv, out, drop_keys=[NO_PRINTING])

    remaining = [r for r in _rows(out) if r[0] == "46986414"]
    assert [r[1] for r in remaining] == ["SDY-006"]


def test_dropping_the_unprinted_row_does_not_drop_the_printed_one(fixture_csv, tmp_path):
    """And the inverse, so the match is not merely matching everything."""
    out = tmp_path / "out.csv"
    revise_to_csv(fixture_csv, out, drop_keys=[PRINTED])

    remaining = [r for r in _rows(out) if r[0] == "46986414"]
    assert [r[1] for r in remaining] == [None]


def test_a_key_that_matches_nothing_drops_nothing(fixture_csv, tmp_path):
    out = tmp_path / "out.csv"
    revise_to_csv(fixture_csv, out, drop_keys=[{**PRINTED, "language": "PT"}])
    assert len(_rows(out)) == len(_rows(fixture_csv))


def test_the_revised_file_is_an_export_like_any_other(fixture_csv, tmp_path):
    """Including the two rows that exercise the escaping in both directions."""
    out = tmp_path / "out.csv"
    revise_to_csv(fixture_csv, out, drop_keys=[PRINTED])

    assert out.read_text(encoding="utf-8").splitlines()[0] == ",".join(COLLECTION_COLUMNS)
    with open_collection(out) as con:
        names = [n for (n,) in con.execute("SELECT name FROM collection").fetchall()]
    assert "=Test Formula Card" in names
    assert 'Nibiru, the "Primal" Being' in names


def test_revising_reads_the_source_and_writes_only_the_target(fixture_csv, tmp_path):
    original = fixture_csv.read_bytes()
    revise_to_csv(fixture_csv, tmp_path / "out.csv", drop_keys=[PRINTED])
    assert fixture_csv.read_bytes() == original


def test_dropping_every_row_leaves_a_loadable_header_only_export(fixture_csv, tmp_path):
    """The assumption the whole delete path rests on."""
    out = tmp_path / "out.csv"
    with open_collection(fixture_csv) as con:
        every = con.execute(
            "SELECT passcode, set_code, set_name, rarity, condition, edition, language "
            "FROM collection"
        ).fetchall()
    keys = [
        dict(
            zip(
                ("passcode", "set_code", "set_name", "rarity", "condition", "edition", "language"),
                row,
            )
        )
        for row in every
    ]

    revise_to_csv(fixture_csv, out, drop_keys=keys)

    assert out.read_text(encoding="utf-8").strip() == ",".join(COLLECTION_COLUMNS)
    with open_collection(out) as con:
        assert con.execute("SELECT COUNT(*) FROM collection").fetchone()[0] == 0


def test_a_staged_replacement_is_folded_in_after_the_drop(fixture_csv, tmp_path):
    staged = tmp_path / "staged.csv"
    write_staged([_replacement(PRINTED, condition="GOOD", quantity=9)], staged)

    out = tmp_path / "out.csv"
    revise_to_csv(fixture_csv, out, drop_keys=[PRINTED], incoming=staged)

    changed = [r for r in _rows(out) if r[0] == "46986414" and r[1] == "SDY-006"]
    assert [(r[2], r[5]) for r in changed] == [("GOOD", 9)]


# --- write_staged carrying an acquisition date -------------------------------


def test_a_supplied_created_at_is_kept_and_updated_at_is_still_now(tmp_path):
    staged = tmp_path / "staged.csv"
    write_staged(
        [_replacement(PRINTED, created_at="2020-05-01T00:00:00Z")],
        staged,
    )
    with open_collection(staged) as con:
        created, updated = con.execute(
            "SELECT created_at_raw, updated_at_raw FROM collection"
        ).fetchone()
    assert created == "2020-05-01T00:00:00Z"
    assert updated != created


# --- editing, through the API ------------------------------------------------


def test_editing_a_row_keeps_when_it_was_acquired_and_moves_when_it_was_touched(client):
    before = [r for r in _owned(client, "46986414") if r["set_code"] == "SDY-006"][0]
    assert _edit(client, PRINTED, condition="GOOD", quantity=2).status_code == 200

    after = [r for r in _owned(client, "46986414") if r["set_code"] == "SDY-006"][0]
    assert after["condition"] == "GOOD"
    assert after["created_at"] == before["created_at"]
    assert after["created_at"].startswith("2026-01-04")
    assert after["updated_at"] > before["updated_at"]


def test_editing_only_the_quantity_sets_it_rather_than_adding_to_it(client):
    """The claim that makes the drop-then-fold order the right one."""
    assert _edit(client, PRINTED, quantity=5).status_code == 200

    row = [r for r in _owned(client, "46986414") if r["set_code"] == "SDY-006"][0]
    assert row["quantity"] == 5  # not 2 + 5


def test_editing_a_row_into_one_already_owned_merges_them(client):
    """The scanner's rule: an edit onto a combination you own is not a duplicate."""
    # The dialog sends the row's own quantity back, so the two copies move too.
    assert _edit(client, PRINTED, **NO_PRINTING, quantity=2).status_code == 200

    rows = _owned(client, "46986414")
    assert len(rows) == 1
    assert rows[0]["set_code"] is None
    assert rows[0]["quantity"] == 6  # the four unprinted plus the two moved onto them
    # Owned since the earlier of the two acquisitions.
    assert rows[0]["created_at"].startswith("2026-01-03")


def test_editing_the_printing_moves_the_row_between_printings(client):
    assert _edit(
        client,
        PRINTED,
        set_code="LOB-005",
        set_name="Legend of Blue Eyes White Dragon",
        rarity="Ultra Rare",
    ).status_code == 200

    codes = sorted((r["set_code"] or "") for r in _owned(client, "46986414"))
    assert codes == ["", "LOB-005"]


def test_editing_a_row_onto_a_different_passcode_moves_the_card(client):
    assert _edit(client, PRINTED, passcode="4041", name="Mystical Elf").status_code == 200

    assert client.get("/api/cards/46986414").json()["row_count"] == 1
    assert any(r["set_code"] == "SDY-006" for r in _owned(client, "4041"))


def test_an_edit_keeps_the_notes_it_is_given(client):
    assert _edit(client, PRINTED, notes="sleeved").status_code == 200
    row = [r for r in _owned(client, "46986414") if r["set_code"] == "SDY-006"][0]
    assert row["notes"] == "sleeved"


@pytest.mark.parametrize(
    "bad",
    [
        {"quantity": 0},
        {"condition": "PRISTINE"},
        {"edition": "SECOND"},
        {"passcode": "not-a-number"},
        {"name": ""},
        {"language": ""},
    ],
)
def test_an_edit_whose_replacement_breaks_the_contract_is_refused(client, tmp_path, bad):
    before = client.get("/api/cards").json()["total_copies"]
    assert _edit(client, PRINTED, **bad).status_code == 422
    assert client.get("/api/cards").json()["total_copies"] == before
    assert not list((tmp_path / "data").glob("ygo_collection_*.csv"))


def test_an_edit_of_a_row_that_is_no_longer_there_is_a_404(client, tmp_path):
    assert _edit(client, {**PRINTED, "condition": "MINT"}, quantity=2).status_code == 404
    assert not list((tmp_path / "data").glob("ygo_collection_*.csv"))


def test_editing_with_no_collection_loaded_is_a_404(empty_client):
    assert _edit(empty_client, PRINTED, quantity=2).status_code == 404


def test_a_language_the_loader_never_normalized_is_still_addressable(
    fixture_csv, fixture_dump, tmp_path, monkeypatch
):
    """The reason EntryKey is not validated like NewEntry.

    ``language`` is free-form by contract and the loader leaves it exactly as the
    CSV spells it. A key that trimmed or upper-cased would make this row show on
    the card page and refuse every attempt to change it.
    """
    odd = tmp_path / "odd.csv"
    lines = fixture_csv.read_text(encoding="utf-8").splitlines()
    header, first, rest = lines[0], lines[1], lines[2:]
    odd.write_text("\n".join([header, first.replace(",EN,", ", en ,"), *rest]) + "\n", "utf-8")

    patch_catalogue_paths(monkeypatch, build_catalogue(fixture_dump, tmp_path))
    monkeypatch.setattr("ygo_explorer.api.routes.collection.DATA_DIR", tmp_path / "data")
    with TestClient(create_app(odd)) as odd_client:
        served = _owned(odd_client, "00004041")[0]
        assert served["language"] == " en "

        key = {
            "passcode": "00004041",
            "set_code": "LOB-EN004",
            "set_name": "Legend of Blue Eyes White Dragon",
            "rarity": "Super Rare",
            "condition": "MINT",
            "edition": "FIRST",
            "language": " en ",
        }
        response = odd_client.patch(
            "/api/collection/entries",
            json={"key": key, "row": _replacement(key, name="Mystical Elf", language="EN")},
        )
        assert response.status_code == 200
        assert _owned(odd_client, "00004041")[0]["language"] == "EN"


def test_a_failed_edit_leaves_the_previous_collection_loaded(client, tmp_path, monkeypatch):
    before = client.get("/api/collection/status").json()

    def explode(*args, **kwargs):
        raise RuntimeError("disk gave up")

    monkeypatch.setattr("ygo_explorer.api.routes.collection.revise_to_csv", explode)
    assert _edit(client, PRINTED, quantity=4).status_code == 422

    assert client.get("/api/collection/status").json() == before
    assert not list((tmp_path / "data").glob("ygo_collection_*.csv"))


# --- deleting, through the API -----------------------------------------------


def test_deleting_a_row_removes_exactly_its_copies(client):
    before = client.get("/api/cards").json()
    assert _delete(client, PRINTED).status_code == 200
    after = client.get("/api/cards").json()

    assert after["total_copies"] == before["total_copies"] - 2
    assert after["total_cards"] == before["total_cards"]  # the unprinted row remains
    assert [r["set_code"] for r in _owned(client, "46986414")] == [None]


def test_deleting_the_last_row_of_a_card_makes_the_card_a_404(client):
    key = {
        "passcode": "47355498",
        "set_code": "AST-EN049",
        "set_name": "Ancient Sanctuary",
        "rarity": "Rare",
        "condition": "EXCELLENT",
        "edition": "UNLIMITED",
        "language": "FR",
    }
    assert _delete(client, key).status_code == 200
    assert client.get("/api/cards/47355498").status_code == 404


def test_deleting_every_row_leaves_a_loaded_but_empty_collection(client):
    """Not the same as having no collection: there is an export, it is just empty."""
    rows = client.get("/api/cards", params={"limit": 100}).json()["items"]
    keys = [
        {
            "passcode": card["passcode"],
            "set_code": row["set_code"],
            "set_name": row["set_name"],
            "rarity": row["rarity"],
            "condition": row["condition"],
            "edition": row["edition"],
            "language": row["language"],
        }
        for card in rows
        for row in _owned(client, card["passcode"])
    ]
    assert _delete(client, *keys).status_code == 200

    status = client.get("/api/collection/status").json()
    assert status["has_collection"] is True
    assert status["collection_rows"] == 0

    listing = client.get("/api/cards").json()
    assert listing["items"] == []
    assert listing["total_copies"] == 0


def test_a_delete_writes_a_new_export_and_touches_no_existing_one(client, fixture_csv, tmp_path):
    original = fixture_csv.read_bytes()
    assert _delete(client, PRINTED).status_code == 200

    written = sorted((tmp_path / "data").glob("ygo_collection_*.csv"))
    assert len(written) == 1
    assert fixture_csv.read_bytes() == original
    assert client.get("/api/collection/status").json()["csv_path"] == str(written[0])


def test_deleting_a_key_that_matches_nothing_is_a_404_and_writes_nothing(client, tmp_path):
    assert _delete(client, {**PRINTED, "rarity": "Common"}).status_code == 404
    assert not list((tmp_path / "data").glob("ygo_collection_*.csv"))


def test_one_stale_key_refuses_the_whole_delete(client, tmp_path):
    before = client.get("/api/cards").json()["total_copies"]
    assert _delete(client, PRINTED, {**NO_PRINTING, "language": "PT"}).status_code == 404

    assert client.get("/api/cards").json()["total_copies"] == before
    assert not list((tmp_path / "data").glob("ygo_collection_*.csv"))


def test_a_delete_with_no_keys_is_refused(client):
    assert _delete(client).status_code == 422


def test_a_guarded_name_survives_a_delete_of_another_row(client, tmp_path):
    assert _delete(client, PRINTED).status_code == 200
    assert client.get("/api/cards/00000001").json()["name"] == "=Test Formula Card"
    assert "'=Test Formula Card" in _newest(tmp_path).read_text(encoding="utf-8")


def test_deleting_with_no_collection_loaded_is_a_404(empty_client):
    assert _delete(empty_client, PRINTED).status_code == 404


# --- the way back out --------------------------------------------------------


def test_the_export_is_the_loaded_file_byte_for_byte(client, fixture_csv):
    response = client.get("/api/collection/export")
    assert response.status_code == 200
    assert response.content == fixture_csv.read_bytes()
    assert response.headers["content-type"].startswith("text/csv")


def test_the_export_is_named_after_the_file_it_serves(client, fixture_csv):
    disposition = client.get("/api/collection/export").headers["content-disposition"]
    assert fixture_csv.name in disposition


def test_the_export_follows_the_collection_after_a_write(client, tmp_path):
    assert _delete(client, PRINTED).status_code == 200
    assert client.get("/api/collection/export").content == _newest(tmp_path).read_bytes()


def test_the_export_uploads_straight_back_in(client):
    """What comes down is an export like any other — the point of serving the file."""
    before = client.get("/api/cards").json()
    downloaded = client.get("/api/collection/export").content

    response = client.post(
        "/api/collection/upload",
        files={"file": ("collection.csv", downloaded, "text/csv")},
        data={"mode": "replace"},
    )
    assert response.status_code == 200
    assert client.get("/api/cards").json()["total_copies"] == before["total_copies"]


def test_exporting_with_no_collection_loaded_is_a_404(empty_client):
    assert empty_client.get("/api/collection/export").status_code == 404
