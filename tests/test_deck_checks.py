"""Saved deck checks, and the owned flag that holds a deck's copies.

The fixture collection owns six Dark Magicians, which is what every scenario
here contends over.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import build_catalogue, patch_catalogue_paths
from ygo_explorer.api.main import create_app

SIX = "Main Deck:\n6 Dark Magician\n"
ONE = "Main Deck:\n1 Dark Magician\n"
FOUR = "Main Deck:\n4 Dark Magician\n"


@pytest.fixture
def make_client(fixture_csv: Path, fixture_dump: Path, tmp_path: Path, monkeypatch):
    patch_catalogue_paths(monkeypatch, build_catalogue(fixture_dump, tmp_path))
    from ygo_explorer.pricing.snapshots import SnapshotStore

    monkeypatch.setattr(
        "ygo_explorer.api.main.SnapshotStore",
        lambda: SnapshotStore(tmp_path / "snapshots.parquet"),
    )
    return lambda: TestClient(create_app(fixture_csv))


@pytest.fixture
def client(make_client):
    with make_client() as c:
        yield c


def check(client, text: str) -> dict:
    response = client.post("/api/deck/analyze", json={"text": text})
    assert response.status_code == 200, response.text
    return response.json()


def flag(client, check_id: str, owned: bool = True) -> dict:
    response = client.patch(f"/api/deck/checks/{check_id}", json={"owned": owned})
    assert response.status_code == 200, response.text
    return response.json()


def rename(client, check_id: str, name: str) -> dict:
    return client.patch(f"/api/deck/checks/{check_id}", json={"name": name}).json()


def reopen(client, check_id: str) -> dict:
    response = client.get(f"/api/deck/checks/{check_id}")
    assert response.status_code == 200, response.text
    return response.json()


def dark_magician(analysis: dict) -> dict:
    return next(c for c in analysis["cards"] if c["name"] == "Dark Magician")


# --- saving ------------------------------------------------------------------


def test_every_check_is_saved(client):
    body = check(client, SIX)
    assert body["check"]["id"]
    assert body["check"]["owned"] is False
    assert body["text"] == SIX
    listed = client.get("/api/deck/checks").json()
    assert [c["id"] for c in listed] == [body["check"]["id"]]


def test_checking_the_same_list_again_keeps_one_entry_and_its_flag(client):
    first = check(client, SIX)["check"]
    rename(client, first["id"], "Dark deck")
    flag(client, first["id"])

    again = check(client, "Main Deck:\r\n6 Dark Magician   \r\n\r\n")["check"]
    assert again["id"] == first["id"]
    assert again["name"] == "Dark deck"
    assert again["owned"] is True
    assert len(client.get("/api/deck/checks").json()) == 1


def test_a_rejected_check_saves_nothing(client):
    assert client.post("/api/deck/analyze", json={"text": "ydke://!!"}).status_code == 422
    assert (
        client.post(
            "/api/deck/analyze", json={"text": SIX, "source_field": "made_up"}
        ).status_code
        == 422
    )
    assert client.get("/api/deck/checks").json() == []


def test_the_history_is_newest_first(client):
    a = check(client, SIX)["check"]["id"]
    b = check(client, ONE)["check"]["id"]
    assert [c["id"] for c in client.get("/api/deck/checks").json()] == [b, a]


def test_rename_and_delete(client):
    c = check(client, SIX)["check"]["id"]
    assert rename(client, c, "  Spellcasters  ")["name"] == "Spellcasters"
    assert client.patch(f"/api/deck/checks/{c}", json={"name": "   "}).status_code == 422
    assert client.delete(f"/api/deck/checks/{c}").status_code == 204
    assert client.get("/api/deck/checks").json() == []
    assert client.delete(f"/api/deck/checks/{c}").status_code == 404


def test_an_unknown_check_is_404(client):
    assert client.get("/api/deck/checks/nope").status_code == 404
    assert client.patch("/api/deck/checks/nope", json={"owned": True}).status_code == 404


def test_checks_and_flags_survive_a_restart(make_client):
    with make_client() as first:
        c = check(first, SIX)["check"]["id"]
        rename(first, c, "Kept")
        flag(first, c)
    with make_client() as second:
        listed = second.get("/api/deck/checks").json()
        assert [(x["id"], x["name"], x["owned"]) for x in listed] == [(c, "Kept", True)]
        assert dark_magician(check(second, ONE))["missing"] == 1


# --- holding copies ----------------------------------------------------------


def test_a_flagged_deck_holds_its_copies_from_the_next_check(client):
    a = check(client, SIX)["check"]
    rename(client, a["id"], "A")
    flag(client, a["id"])

    b = check(client, ONE)
    card = dark_magician(b)
    assert card["owned"] == 6, "owned is still the whole collection"
    assert card["held_elsewhere"] == 6
    assert card["held_by"] == ["A"]
    assert card["missing"] == 1
    assert b["total_owned"] == 0 and b["total_missing"] == 1

    flag(client, a["id"], owned=False)
    b = reopen(client, b["check"]["id"])
    assert dark_magician(b)["missing"] == 0
    assert dark_magician(b)["held_by"] == []


def test_a_flagged_deck_still_counts_its_own_copies(client):
    a = check(client, SIX)["check"]["id"]
    held = flag(client, a)
    assert held["copies_held"] == 6
    body = reopen(client, a)
    assert body["total_missing"] == 0
    assert dark_magician(body)["held_elsewhere"] == 0


def test_the_first_deck_flagged_wins_a_contested_copy(client):
    four = check(client, FOUR)["check"]["id"]
    rename(client, four, "Four")
    one = check(client, ONE)["check"]["id"]
    rename(client, one, "One")
    six = check(client, SIX)["check"]["id"]

    flag(client, one)
    flag(client, four)
    # One claims 1, Four claims 4: one copy left for anyone else.
    assert reopen(client, one)["total_missing"] == 0
    assert reopen(client, four)["total_missing"] == 0
    rest = dark_magician(reopen(client, six))
    assert rest["held_elsewhere"] == 5
    assert rest["held_by"] == ["One", "Four"]
    assert rest["missing"] == 5

    # Flag the six-of last: it gets only the one copy left over.
    flag(client, six)
    assert reopen(client, six)["total_missing"] == 5
    listed = {c["id"]: c for c in client.get("/api/deck/checks").json()}
    assert listed[six]["copies_held"] == 1
    assert listed[four]["copies_held"] == 4


def test_reflagging_goes_to_the_back_of_the_line(client):
    six = check(client, SIX)["check"]["id"]
    one = check(client, ONE)["check"]["id"]
    flag(client, six)
    flag(client, one)
    assert reopen(client, one)["total_missing"] == 1

    flag(client, six, owned=False)
    flag(client, six)
    assert reopen(client, one)["total_missing"] == 0
    assert reopen(client, six)["total_missing"] == 1


def test_deleting_a_flagged_deck_frees_its_copies(client):
    a = check(client, SIX)["check"]["id"]
    flag(client, a)
    b = check(client, ONE)["check"]["id"]
    assert reopen(client, b)["total_missing"] == 1
    client.delete(f"/api/deck/checks/{a}")
    assert reopen(client, b)["total_missing"] == 0


def test_owned_plus_missing_is_needed_while_copies_are_held(client):
    flag(client, check(client, FOUR)["check"]["id"])
    body = check(client, SIX)
    assert body["total_owned"] + body["total_missing"] == body["total_needed"] == 6
    assert body["total_owned"] == 2


def test_the_history_reports_live_counts(client):
    a = check(client, SIX)["check"]["id"]
    b = check(client, ONE)["check"]["id"]
    flag(client, a)
    listed = {c["id"]: c for c in client.get("/api/deck/checks").json()}
    assert listed[a]["total_missing"] == 0 and listed[a]["copies_held"] == 6
    assert listed[b]["total_missing"] == 1 and listed[b]["copies_held"] == 0
    assert listed[b]["total_needed"] == 1


# --- the file itself ---------------------------------------------------------


def test_an_unreadable_file_is_set_aside_not_overwritten(tmp_path: Path):
    from ygo_explorer.deck.history import DeckCheckStore

    path = tmp_path / "deck_checks.json"
    path.write_text("{ not json", encoding="utf-8")
    store = DeckCheckStore(path)
    assert store.list() == []
    aside = list(tmp_path.glob("deck_checks.json.unreadable-*"))
    assert len(aside) == 1 and aside[0].read_text(encoding="utf-8") == "{ not json"


def test_flags_set_in_the_same_instant_still_have_an_order(tmp_path: Path, monkeypatch):
    from datetime import datetime, timezone

    from ygo_explorer.deck import history

    frozen = datetime(2026, 11, 5, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(history, "datetime", Clock)
    store = history.DeckCheckStore(tmp_path / "deck_checks.json")
    ids = [store.record(f"Main Deck:\n{n} Dark Magician", "plaintext", []).id for n in (1, 2, 3)]
    for check_id in reversed(ids):
        store.update(check_id, owned=True)
    assert [c.id for c in store.flagged()] == list(reversed(ids))
