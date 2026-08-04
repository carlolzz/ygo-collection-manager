"""The valuation, deck, collection-status and image endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ygo_explorer.api.main import create_app
from ygo_explorer.catalogue.normalize import normalize_dump

_FIXTURES = Path(__file__).parent / "fixtures"
YDKE = (_FIXTURES / "deck_fixture.ydke.txt").read_text(encoding="utf-8").strip()
PLAINTEXT = (_FIXTURES / "deck_fixture.txt").read_text(encoding="utf-8")


def _wire_catalogue(fixture_dump: Path, tmp_path: Path, monkeypatch) -> None:
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


@pytest.fixture
def client(fixture_csv: Path, fixture_dump: Path, tmp_path: Path, monkeypatch):
    _wire_catalogue(fixture_dump, tmp_path, monkeypatch)
    monkeypatch.setattr("ygo_explorer.api.main.SnapshotStore", lambda: _store(tmp_path))
    with TestClient(create_app(fixture_csv)) as c:
        yield c


def _store(tmp_path: Path):
    from ygo_explorer.pricing.snapshots import SnapshotStore

    return SnapshotStore(tmp_path / "snapshots.parquet")


@pytest.fixture
def empty_client(fixture_dump: Path, tmp_path: Path, monkeypatch):
    """No collection at all — the container's first-run state."""
    _wire_catalogue(fixture_dump, tmp_path, monkeypatch)
    monkeypatch.setattr("ygo_explorer.api.main.SnapshotStore", lambda: _store(tmp_path))
    with TestClient(create_app(tmp_path / "no-such-export.csv")) as c:
        yield c


# --- valuation ---------------------------------------------------------------


def test_collection_valuation_states_its_currency_and_caveat(client):
    """The no-argument run is Cardmarket, and therefore EUR."""
    body = client.post("/api/valuation/collection").json()
    assert body["total"]["currency"] == "EUR"
    assert body["is_estimate"] is True
    assert "Estimate in EUR" in body["caveat"]
    assert body["source_field"] == "cardmarket_price"


def test_valuation_reports_the_basis_split(client):
    # Explicitly USD: the per-printing basis only exists there, so the default
    # EUR run could not exercise this split.
    body = client.post(
        "/api/valuation/collection?source_field=tcgplayer_price"
    ).json()
    total_rows = (
        body["per_printing_rows"] + body["per_passcode_rows"] + body["unpriced_rows"]
    )
    assert total_rows == 8
    assert body["per_printing_rows"] > 0
    assert body["unpriced_rows"] >= 1


def test_valuation_amounts_are_strings_not_json_floats(client):
    """A float total would round cents in transit."""
    body = client.post("/api/valuation/collection").json()
    assert isinstance(body["total"]["amount"], str)
    priced = [r for r in body["rows"] if r["subtotal"]]
    assert all(isinstance(r["subtotal"]["amount"], str) for r in priced)


def test_valuation_surfaces_edition_without_pricing_it(client):
    body = client.post("/api/valuation/collection").json()
    row = next(r for r in body["rows"] if r["set_code"] == "SDY-006")
    assert row["edition"] == "FIRST"
    assert row["multiplier"] == "0.40", "condition is priced; edition is not"


def test_single_card_valuation_covers_only_that_card(client):
    body = client.post("/api/valuation/card/46986414").json()
    assert {r["passcode"] for r in body["rows"]} == {"46986414"}


def test_valuing_an_unowned_card_is_404(client):
    assert client.post("/api/valuation/card/89631139").status_code == 404


def test_an_unknown_price_field_is_rejected(client):
    response = client.post("/api/valuation/collection?source_field=made_up")
    assert response.status_code == 422
    assert "one currency" in response.json()["detail"]


def test_a_eur_run_reports_eur_and_no_printing_refinement(client):
    body = client.post("/api/valuation/collection?source_field=cardmarket_price").json()
    assert body["total"]["currency"] == "EUR"
    assert body["per_printing_rows"] == 0, "set_price is USD-only"


def test_valuation_is_a_post_not_a_get(client):
    assert client.get("/api/valuation/collection").status_code == 405


# --- deck --------------------------------------------------------------------


def test_deck_analyze_accepts_a_ydke_code(client):
    body = client.post("/api/deck/analyze", json={"text": YDKE}).json()
    assert body["source_format"] == "ydke"
    assert body["zone_counts"] == {"main": 10, "extra": 2, "side": 3}
    assert body["unresolved"] == []


def test_deck_analyze_accepts_plaintext(client):
    body = client.post("/api/deck/analyze", json={"text": PLAINTEXT}).json()
    assert body["source_format"] == "plaintext"
    assert body["zone_counts"] == {"main": 10, "extra": 2, "side": 3}


def test_the_two_formats_return_identical_answers(client):
    a = client.post("/api/deck/analyze", json={"text": YDKE}).json()
    b = client.post("/api/deck/analyze", json={"text": PLAINTEXT}).json()
    for field in ("total_needed", "total_owned", "total_missing", "estimated_cost"):
        assert a[field] == b[field], f"{field} disagrees between the two exports"


def test_deck_reports_missing_counts_and_a_cost(client):
    body = client.post("/api/deck/analyze", json={"text": YDKE}).json()
    assert body["total_needed"] == 15
    assert body["total_owned"] + body["total_missing"] == body["total_needed"]
    assert body["estimated_cost"]["currency"] == "EUR"
    assert "playable copy" in body["caveat"]


def test_deck_lists_unresolved_lines_rather_than_dropping_them(client):
    body = client.post(
        "/api/deck/analyze", json={"text": "Main Deck:\n3 Not A Real Card\n"}
    ).json()
    assert body["unresolved"] == ["Not A Real Card"]
    assert "left out" in body["caveat"]


def test_a_malformed_deck_is_422_with_a_reason(client):
    response = client.post("/api/deck/analyze", json={"text": "ydke://!!"})
    assert response.status_code == 422


def test_deck_costs_in_the_requested_currency(client):
    body = client.post(
        "/api/deck/analyze", json={"text": YDKE, "source_field": "tcgplayer_price"}
    ).json()
    assert body["currency"] == "USD"
    assert body["estimated_cost"]["currency"] == "USD"


def test_an_unknown_deck_price_field_is_422_not_500(client):
    response = client.post(
        "/api/deck/analyze", json={"text": YDKE, "source_field": "made_up"}
    )
    assert response.status_code == 422


def test_deck_analysis_touches_no_network(client, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("deck analysis attempted a network request")

    monkeypatch.setattr("httpx.AsyncClient.get", explode)
    assert client.post("/api/deck/analyze", json={"text": YDKE}).status_code == 200


# --- collection status and the empty state -----------------------------------


def test_collection_status_reports_a_loaded_export(client):
    body = client.get("/api/collection/status").json()
    assert body["has_collection"] is True
    assert body["collection_rows"] == 8


def test_the_app_starts_without_any_export(empty_client):
    """The container's first run: an empty mount must not be a crash."""
    body = empty_client.get("/api/collection/status").json()
    assert body["has_collection"] is False
    assert "upload" in body["message"].lower() or "add a csv" in body["message"].lower()


def test_endpoints_return_empty_results_rather_than_500_without_an_export(empty_client):
    assert empty_client.get("/api/health").json() == {"status": "ok"}
    page = empty_client.get("/api/cards").json()
    assert page["total_cards"] == 0 and page["items"] == []
    stats = empty_client.get("/api/stats").json()
    assert stats["total_copies"] == 0 and stats["distinct_cards"] == 0
    assert empty_client.get("/api/meta/filters").status_code == 200
    assert empty_client.get("/api/catalogue/status").status_code == 200


def test_valuing_an_empty_collection_is_zero_not_an_error(empty_client):
    body = empty_client.post("/api/valuation/collection").json()
    assert body["total"]["amount"] == "0.00"
    assert body["rows"] == []


def test_a_deck_against_an_empty_collection_is_entirely_missing(empty_client):
    body = empty_client.post("/api/deck/analyze", json={"text": YDKE}).json()
    assert body["total_owned"] == 0
    assert body["total_missing"] == body["total_needed"] == 15


def test_uploading_an_export_loads_it(empty_client, fixture_csv):
    response = empty_client.post(
        "/api/collection/upload",
        files={"file": ("export.csv", fixture_csv.read_bytes(), "text/csv")},
    )
    assert response.status_code == 200
    assert response.json()["has_collection"] is True
    assert empty_client.get("/api/cards").json()["total_cards"] == 7


def test_uploading_something_that_is_not_an_export_is_rejected(empty_client):
    response = empty_client.post(
        "/api/collection/upload",
        files={"file": ("junk.csv", b"a,b,c\r\n1,2,3\r\n", "text/csv")},
    )
    assert response.status_code == 422
    assert empty_client.get("/api/collection/status").json()["has_collection"] is False


def test_a_rejected_upload_does_not_take_a_good_one_with_it(empty_client, fixture_csv):
    """Both land in the same second, so they must not land on the same path.

    They used to: the loser was overwritten, then deleted by the rollback, and a
    typo'd second upload silently destroyed the collection already loaded.
    """
    good = empty_client.post(
        "/api/collection/upload",
        files={"file": ("export.csv", fixture_csv.read_bytes(), "text/csv")},
    )
    assert good.status_code == 200
    loaded = good.json()["csv_path"]

    bad = empty_client.post(
        "/api/collection/upload",
        files={"file": ("junk.csv", b"a,b,c\r\n1,2,3\r\n", "text/csv")},
    )
    assert bad.status_code == 422

    status = empty_client.get("/api/collection/status").json()
    assert status["has_collection"] is True
    assert status["csv_path"] == loaded
    assert empty_client.get("/api/cards").json()["total_cards"] == 7


# --- images ------------------------------------------------------------------


def test_a_card_with_no_cached_art_gets_a_placeholder_not_a_broken_image(
    client, monkeypatch
):
    async def no_network(self, *args, **kwargs):
        raise AssertionError("image endpoint must not fetch during this test")

    monkeypatch.setattr("ygo_explorer.images.ImageCache.fetch", no_network)
    monkeypatch.setattr("ygo_explorer.images.ImageCache.known_missing", lambda s, p: True)
    response = client.get("/api/images/46986414")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg")
