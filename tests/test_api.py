"""Build step 3: the read endpoints, over the fixture ledger and fixture dump."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import build_catalogue, patch_catalogue_paths
from ygo_explorer.api.main import create_app
from ygo_explorer.catalogue.dump import DumpProgress


@pytest.fixture
def client(fixture_csv: Path, fixture_dump: Path, tmp_path: Path, monkeypatch):
    """A client whose catalogue is the fixture dump, not whatever is cached.

    The defaults are patched rather than passed through, so the app under test
    is wired exactly as it is in production.
    """
    patch_catalogue_paths(monkeypatch, build_catalogue(fixture_dump, tmp_path))

    with TestClient(create_app(fixture_csv)) as c:
        yield c


# --- totals ------------------------------------------------------------------


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_unfiltered_totals_match_the_ledger(client):
    page = client.get("/api/cards").json()
    assert page["total_copies"] == 19
    assert page["total_cards"] == 7
    assert len(page["items"]) == 7


def test_stats_totals_agree_with_the_card_list(client):
    stats = client.get("/api/stats").json()
    page = client.get("/api/cards").json()
    assert stats["total_copies"] == page["total_copies"] == 19
    assert stats["distinct_cards"] == page["total_cards"] == 7
    assert stats["collection_rows"] == 8


def test_stats_counts_rows_without_a_printing_inside_the_total(client):
    stats = client.get("/api/stats").json()
    assert stats["copies_without_printing"] == 5
    assert stats["total_copies"] == 19, "no-printing copies belong in the total"


def test_sets_represented_ignores_the_empty_ones(client):
    assert client.get("/api/stats").json()["sets_represented"] == 6


# --- name search -------------------------------------------------------------


@pytest.mark.parametrize("query", ["necrovalley", "Nécrovalley", "NECROVALLEY", "crova"])
def test_name_search_is_accent_and_case_insensitive(client, query):
    page = client.get("/api/cards", params={"q": query}).json()
    assert [i["name"] for i in page["items"]] == ["Nécrovalley"]


def test_name_search_matches_a_name_that_needed_quoting(client):
    page = client.get("/api/cards", params={"q": "primal"}).json()
    assert page["items"][0]["name"] == 'Nibiru, the "Primal" Being'


def test_name_search_matches_a_formula_guarded_name_without_the_apostrophe(client):
    page = client.get("/api/cards", params={"q": "=Test Formula"}).json()
    assert [i["name"] for i in page["items"]] == ["=Test Formula Card"]


# --- filters compose ---------------------------------------------------------


def test_an_ownership_filter_narrows_the_result(client):
    everything = client.get("/api/cards").json()
    filtered = client.get("/api/cards", params={"condition": "POOR"}).json()
    assert filtered["total_cards"] < everything["total_cards"]
    assert filtered["total_cards"] == 1


def test_a_catalogue_filter_narrows_the_result(client):
    filtered = client.get("/api/cards", params={"attribute": "LIGHT"}).json()
    assert {i["name"] for i in filtered["items"]} == {"Mystical Elf", "Nibiru, the \"Primal\" Being"}


def test_two_filters_are_narrower_than_one(client):
    one = client.get("/api/cards", params={"type": "Normal Monster"}).json()
    two = client.get(
        "/api/cards", params={"type": "Normal Monster", "condition": "POOR"}
    ).json()
    assert one["total_cards"] == 2
    assert two["total_cards"] == 1
    assert two["total_cards"] < one["total_cards"]


def test_ownership_and_catalogue_filters_compose_identically(client):
    """The caller cannot tell which source a filter came from."""
    mixed = client.get(
        "/api/cards", params={"attribute": "DARK", "language": "DE"}
    ).json()
    assert mixed["total_cards"] == 1
    assert mixed["items"][0]["name"] == "Dark Magician"


def test_a_card_summary_lists_every_language_it_is_held_in(client):
    """Not functionally dependent on the passcode, unlike the catalogue columns:
    the fixture holds Dark Magician in English and in German."""
    items = client.get("/api/cards").json()["items"]
    by_name = {item["name"]: item for item in items}
    assert by_name["Dark Magician"]["languages"] == ["DE", "EN"]
    assert by_name["Mystical Elf"]["languages"] == ["EN"]


def test_a_filtered_summary_still_lists_only_the_matching_languages(client):
    """The rollup happens after the filter, so a language filter narrows it."""
    items = client.get("/api/cards", params={"language": "DE"}).json()["items"]
    assert [item["languages"] for item in items] == [["DE"]]


def test_multiple_values_of_one_filter_are_ored(client):
    both = client.get("/api/cards", params=[("condition", "POOR"), ("condition", "MINT")]).json()
    assert both["total_cards"] == 2


def test_filtered_totals_describe_the_filtered_rows(client):
    """A condition filter reports the copies in that condition, not the whole stack."""
    page = client.get("/api/cards", params={"condition": "POOR"}).json()
    assert page["items"][0]["passcode"] == "46986414"
    assert page["items"][0]["total_copies"] == 2, "the NEAR_MINT stack of 4 is excluded"
    assert page["total_copies"] == 2


def test_has_printing_false_finds_the_rows_with_an_empty_set_code(client):
    page = client.get("/api/cards", params={"has_printing": "false"}).json()
    assert page["total_copies"] == 5
    assert {i["passcode"] for i in page["items"]} == {"46986414", "99999999"}


def test_level_range_filters(client):
    page = client.get("/api/cards", params={"level_min": 7}).json()
    assert {i["name"] for i in page["items"]} == {
        "Dark Magician",
        'Nibiru, the "Primal" Being',
    }


def test_an_unknown_sort_is_rejected(client):
    assert client.get("/api/cards", params={"sort": "price"}).status_code == 422


def test_sorting_by_copies_puts_the_biggest_stack_first(client):
    page = client.get("/api/cards", params={"sort": "copies"}).json()
    assert page["items"][0]["passcode"] == "46986414"
    assert page["items"][0]["total_copies"] == 6


def test_pagination_does_not_change_the_totals(client):
    page = client.get("/api/cards", params={"limit": 2, "offset": 2}).json()
    assert len(page["items"]) == 2
    assert page["total_cards"] == 7
    assert page["total_copies"] == 19


# --- rows the dump does not know ---------------------------------------------


def test_an_unmatched_card_is_listed_not_dropped(client):
    page = client.get("/api/cards").json()
    unmatched = [i for i in page["items"] if i["passcode"] == "99999999"]
    assert len(unmatched) == 1
    assert unmatched[0]["name"] == "Unlisted Promo Card"
    assert unmatched[0]["in_catalogue"] is False
    assert unmatched[0]["type"] is None


def test_an_unmatched_card_has_a_working_detail_view(client):
    card = client.get("/api/cards/99999999").json()
    assert card["name"] == "Unlisted Promo Card"
    assert card["in_catalogue"] is False
    assert card["printings"] == [], "printings are unknown, not invented"
    assert card["rows"][0]["quantity"] == 1


def test_in_catalogue_filter_isolates_them(client):
    page = client.get("/api/cards", params={"in_catalogue": "false"}).json()
    assert [i["passcode"] for i in page["items"]] == ["99999999"]


# --- detail view -------------------------------------------------------------


def test_detail_lists_every_owned_row_best_condition_first(client):
    card = client.get("/api/cards/46986414").json()
    assert card["total_copies"] == 6
    assert card["row_count"] == 2
    assert [r["condition"] for r in card["rows"]] == ["NEAR_MINT", "POOR"]
    assert [r["quantity"] for r in card["rows"]] == [4, 2]


def test_detail_shows_the_condition_edition_language_breakdown(client):
    rows = client.get("/api/cards/46986414").json()["rows"]
    poor = next(r for r in rows if r["condition"] == "POOR")
    assert (poor["edition"], poor["language"], poor["set_code"]) == (
        "FIRST",
        "DE",
        "SDY-006",
    )
    assert poor["notes"] == "creased corner"


def test_detail_flags_which_catalogue_printings_are_owned(client):
    printings = client.get("/api/cards/46986414").json()["printings"]
    owned = {p["set_code"] for p in printings if p["owned"]}
    assert owned == {"SDY-006"}
    assert {p["set_code"] for p in printings} == {"SDY-006", "LOB-005"}


def test_detail_carries_the_per_printing_price(client):
    printings = client.get("/api/cards/46986414").json()["printings"]
    sdy = next(p for p in printings if p["set_code"] == "SDY-006")
    assert sdy["set_price_usd"] == 9.96
    assert sdy["set_rarity"] == "Ultra Rare"


def test_a_leading_zero_passcode_is_addressable_as_written(client):
    card = client.get("/api/cards/00004041").json()
    assert card["passcode"] == "00004041"
    assert card["name"] == "Mystical Elf"
    assert card["attribute"] == "LIGHT"


def test_the_int_form_of_a_leading_zero_passcode_is_not_a_card(client):
    assert client.get("/api/cards/4041").status_code == 404


def test_an_unowned_passcode_is_404(client):
    response = client.get("/api/cards/89631139")
    assert response.status_code == 404
    assert "89631139" in response.json()["detail"]


# --- filter options ----------------------------------------------------------


def test_filter_options_come_from_the_data(client):
    options = client.get("/api/meta/filters").json()
    assert options["condition"][0] == "MINT", "grades listed best first"
    assert options["condition"][-1] == "POOR"
    assert set(options["language"]) == {"DE", "EN", "FR", "IT", "JP", "KR"}
    assert "Dark Magician" in options["archetype"]
    assert (options["level_min"], options["level_max"]) == (4, 11)


def test_filter_options_exclude_the_empty_values(client):
    options = client.get("/api/meta/filters").json()
    assert None not in options["rarity"]
    assert "" not in options["rarity"]


# --- catalogue status --------------------------------------------------------


def test_catalogue_status_reports_coverage_and_says_what_is_missing(client):
    status = client.get("/api/catalogue/status").json()
    assert status["collection_rows"] == 8
    assert status["matched_rows"] == 7
    assert status["unmatched_rows"] == 1
    assert status["unmatched_passcodes"] == 1


def test_no_endpoint_touches_the_network_on_a_read(client, monkeypatch):
    """Nothing fetches on a page load, a filter change or a scroll."""

    def explode(*args, **kwargs):
        raise AssertionError("a read endpoint attempted a network request")

    monkeypatch.setattr("ygo_explorer.catalogue.dump.fetch_dump", explode)
    for url in (
        "/api/cards",
        "/api/cards?q=dark",
        "/api/cards/46986414",
        "/api/stats",
        "/api/meta/filters",
        "/api/catalogue/status",
    ):
        assert client.get(url).status_code == 200


def test_refresh_is_a_post_not_a_get(client):
    assert client.get("/api/catalogue/refresh").status_code == 405


# --- the refresh job ---------------------------------------------------------


def _poll_until_done(client, job_id, tries=60):
    """The job runs detached, so the test drives it the way the UI does."""
    for _ in range(tries):
        job = client.get(f"/api/catalogue/refresh/{job_id}").json()
        if job["status"] in ("finished", "error"):
            return job
    raise AssertionError(f"job {job_id} never finished: {job}")


def test_refresh_starts_a_job_and_reports_it_to_completion(client, monkeypatch):
    """The request returns when the work starts, not when it ends."""

    async def fake_fetch(**kwargs):
        kwargs["on_progress"](
            DumpProgress(
                phase="cards", language=None, step=1, steps=1,
                downloaded=1_000, expected=1_000,
            )
        )
        return None

    monkeypatch.setattr("ygo_explorer.catalogue.job.fetch_dump", fake_fetch)

    started = client.post("/api/catalogue/refresh")
    assert started.status_code == 202
    job = started.json()
    assert job["status"] in ("pending", "running")

    done = _poll_until_done(client, job["id"])
    assert done["status"] == "finished"
    assert done["error"] is None
    assert done["percent"] == 100.0


def test_two_refreshes_at_once_are_refused(client, monkeypatch):
    """Forty megabytes twice over, from two tabs, helps nobody."""
    # A plain dict rather than an asyncio.Event: the loop runs on the test
    # client's own thread, and Event.set() across threads is not safe.
    gate = {"open": False}

    async def blocked(**kwargs):
        while not gate["open"]:
            await asyncio.sleep(0.01)

    monkeypatch.setattr("ygo_explorer.catalogue.job.fetch_dump", blocked)

    first = client.post("/api/catalogue/refresh").json()
    second = client.post("/api/catalogue/refresh")
    assert second.status_code == 409
    assert first["id"] in second.json()["detail"]

    gate["open"] = True
    assert _poll_until_done(client, first["id"])["status"] == "finished"


def test_a_failed_refresh_reports_why_through_the_job(client, monkeypatch):
    """The endpoint returned long ago; the job is the only route to the screen."""

    async def explode(**kwargs):
        raise RuntimeError("YGOPRODeck said no")

    monkeypatch.setattr("ygo_explorer.catalogue.job.fetch_dump", explode)

    job = client.post("/api/catalogue/refresh").json()
    done = _poll_until_done(client, job["id"])
    assert done["status"] == "error"
    assert "YGOPRODeck said no" in done["error"]


def test_progress_for_an_unknown_job_is_a_404(client):
    assert client.get("/api/catalogue/refresh/nosuchjob").status_code == 404


# --- stats -------------------------------------------------------------------


def test_stats_buckets_report_both_counts(client):
    by_condition = client.get("/api/stats").json()["by_condition"]
    near_mint = next(b for b in by_condition if b["key"] == "NEAR_MINT")
    # Two NEAR_MINT rows: Dark Magician x4 and the unlisted promo x1. The two
    # counts differ here, which is exactly why both are reported.
    assert near_mint["total_copies"] == 5
    assert near_mint["distinct_cards"] == 2
    assert set(by_condition[0]) == {"key", "total_copies", "distinct_cards"}


def test_condition_buckets_are_in_cardmarket_order(client):
    keys = [b["key"] for b in client.get("/api/stats").json()["by_condition"]]
    assert keys == [
        "MINT",
        "NEAR_MINT",
        "EXCELLENT",
        "GOOD",
        "LIGHT_PLAYED",
        "PLAYED",
        "POOR",
    ]


def test_acquisitions_are_bucketed_by_month(client):
    months = client.get("/api/stats").json()["acquisitions_by_month"]
    assert [m["period"] for m in months] == ["2026-01"]
    assert months[0]["total_copies"] == 19


def test_most_held_is_the_long_tail_descending(client):
    most_held = client.get("/api/stats").json()["most_held"]
    copies = [c["total_copies"] for c in most_held]
    assert copies == sorted(copies, reverse=True)
    assert most_held[0]["passcode"] == "46986414"


def test_by_type_bucket_includes_an_unknown_key_for_unmatched_cards(client):
    by_type = client.get("/api/stats").json()["by_type"]
    unknown = [b for b in by_type if b["key"] is None]
    assert unknown and unknown[0]["total_copies"] == 1, (
        "the card the dump does not know still contributes its copy"
    )


def test_an_unknown_api_path_is_404_not_the_spa(client):
    """The SPA catch-all must not swallow API mistakes into a silent 200."""
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
