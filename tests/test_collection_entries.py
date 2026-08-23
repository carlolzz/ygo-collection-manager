"""Adding cards by hand, and the catalogue lookup that feeds the picker.

The claim under test is the one the feature exists to make: three copies of a
card described differently are three rows, three described identically are one
row of quantity three, and either way the file that comes out is an export the
ordinary loader reads back without a special case.

Nothing here touches the network — the picker is served from the fixture dump.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import build_catalogue, patch_catalogue_paths
from ygo_explorer.api.main import create_app
from ygo_explorer.collection.entry import write_staged
from ygo_explorer.collection.loader import (
    FORMULA_TRIGGERS,
    guard_expr,
    guard_text,
    open_collection,
)
from ygo_explorer.collection.schema import COLLECTION_COLUMNS


def _entry(**overrides) -> dict:
    """One valid row. Card Trooper, the card the request was written about."""
    row = {
        "passcode": "85087012",
        "name": "Card Trooper",
        "set_code": "DUSA-EN061",
        "set_name": "Duelist Saga",
        "rarity": "Ultra Rare",
        "condition": "NEAR_MINT",
        "edition": "UNLIMITED",
        "language": "EN",
        "quantity": 1,
        "notes": None,
    }
    row.update(overrides)
    return row


@pytest.fixture
def client(fixture_csv: Path, fixture_dump: Path, tmp_path: Path, monkeypatch):
    """A loaded collection, with saves landing in a throwaway data directory."""
    patch_catalogue_paths(monkeypatch, build_catalogue(fixture_dump, tmp_path))
    monkeypatch.setattr("ygo_explorer.api.routes.collection.DATA_DIR", tmp_path / "data")
    with TestClient(create_app(fixture_csv)) as c:
        yield c


@pytest.fixture
def empty_client(tmp_path: Path, monkeypatch):
    """No export at all — the container's first run, before any CSV exists."""
    monkeypatch.setattr("ygo_explorer.api.routes.collection.DATA_DIR", tmp_path / "data")
    with TestClient(create_app(tmp_path / "no-such-export.csv")) as c:
        yield c


def _add(client: TestClient, *rows: dict):
    return client.post("/api/collection/entries", json={"rows": list(rows)})


def _owned(client: TestClient, passcode: str) -> list[dict]:
    return client.get(f"/api/cards/{passcode}").json()["rows"]


# --- the staged writer -------------------------------------------------------


def test_staged_rows_read_back_through_the_ordinary_loader(tmp_path):
    """The contract test: what is written is an export like any other."""
    staged = tmp_path / "staged.csv"
    write_staged([_entry(), _entry(language="DE")], staged)

    assert staged.read_text(encoding="utf-8").splitlines()[0] == ",".join(COLLECTION_COLUMNS)
    with open_collection(staged) as con:
        rows = con.execute(
            "SELECT passcode, name, language, quantity, notes FROM collection ORDER BY language"
        ).fetchall()
    assert rows == [
        ("85087012", "Card Trooper", "DE", 1, None),
        ("85087012", "Card Trooper", "EN", 1, None),
    ]


def test_absent_optional_columns_become_null_not_the_string_none(tmp_path):
    staged = tmp_path / "staged.csv"
    write_staged([_entry(set_code=None, set_name=None, rarity=None)], staged)
    with open_collection(staged) as con:
        assert con.execute(
            "SELECT set_code, set_name, rarity, notes FROM collection"
        ).fetchone() == (None, None, None, None)


def test_write_staged_refuses_to_write_nothing(tmp_path):
    with pytest.raises(ValueError):
        write_staged([], tmp_path / "staged.csv")


# --- the formula-injection guard, both halves --------------------------------


@pytest.mark.parametrize("trigger", FORMULA_TRIGGERS)
def test_a_name_starting_with_a_formula_trigger_survives_the_round_trip(tmp_path, trigger):
    """``-Ancient Gear`` must not reach a spreadsheet as a formula, or us as a stub."""
    name = f"{trigger}Ancient Gear"
    staged = tmp_path / "staged.csv"
    write_staged([_entry(name=name)], staged)

    assert guard_text(name) == "'" + name
    with open_collection(staged) as con:
        assert con.execute("SELECT name FROM collection").fetchone()[0] == name


def test_guard_text_and_guard_expr_agree(tmp_path):
    """Two implementations of one rule; a drift between them corrupts names."""
    import duckdb

    samples = ["Dark Magician", "-Ancient Gear", "=Test", "+1", "@home", "\tTabbed", ""]
    # Bound once into a subquery: guard_expr repeats its argument four times, so
    # passing '?' straight in would want four copies of the same parameter.
    sql = f"SELECT {guard_expr('v')} FROM (SELECT ? AS v)"
    with duckdb.connect() as con:
        for value in samples:
            expected = guard_text(value or None)
            assert con.execute(sql, [value or None]).fetchone()[0] == expected, value


def test_an_untriggered_name_is_left_exactly_alone():
    assert guard_text("Card Trooper") == "Card Trooper"
    assert guard_text(None) is None


# --- the request: several copies, entered at once ----------------------------


def test_copies_described_differently_become_separate_rows(client):
    """The example from the brief: three Card Troopers, no two alike."""
    response = _add(
        client,
        _entry(language="DE", rarity="Common", set_code="SDMP-DE016", edition="UNLIMITED"),
        _entry(language="IT", rarity="Rare", set_code="LCYW-IT042", edition="FIRST"),
        _entry(language="EN", rarity="Ultra Rare", set_code="DUSA-EN061", edition="UNLIMITED"),
    )
    assert response.status_code == 200

    rows = _owned(client, "85087012")
    assert len(rows) == 3
    assert {r["quantity"] for r in rows} == {1}
    assert sorted(r["language"] for r in rows) == ["DE", "EN", "IT"]
    assert sorted(r["rarity"] for r in rows) == ["Common", "Rare", "Ultra Rare"]
    assert sorted(r["edition"] for r in rows) == ["FIRST", "UNLIMITED", "UNLIMITED"]


def test_copies_described_identically_become_one_row(client):
    assert _add(client, _entry(), _entry(), _entry()).status_code == 200

    rows = _owned(client, "85087012")
    assert len(rows) == 1
    assert rows[0]["quantity"] == 3


def test_adding_a_printing_already_owned_increments_it(client):
    """The scanner's addOrIncrement, reached through the merge."""
    before = _owned(client, "47355498")
    assert (len(before), before[0]["quantity"]) == (1, 3)

    assert _add(
        client,
        _entry(
            passcode="47355498",
            name="Nécrovalley",
            set_code="AST-EN049",
            set_name="Ancient Sanctuary",
            rarity="Rare",
            condition="EXCELLENT",
            edition="UNLIMITED",
            language="FR",
            quantity=2,
        ),
    ).status_code == 200

    after = _owned(client, "47355498")
    assert len(after) == 1
    assert after[0]["quantity"] == 5
    # Owned since the older row said, last touched now.
    assert after[0]["created_at"] < after[0]["updated_at"]
    assert after[0]["created_at"].startswith("2026-01-05")


def test_a_row_with_no_set_recorded_is_kept_apart_from_a_printed_one(client):
    """Skipping the printing is a real answer, not a missing one."""
    assert _add(
        client, _entry(set_code=None, set_name=None, rarity=None), _entry()
    ).status_code == 200

    rows = _owned(client, "85087012")
    assert len(rows) == 2
    assert sorted(r["set_code"] or "" for r in rows) == ["", "DUSA-EN061"]


def test_the_totals_move_by_exactly_what_was_added(client):
    before = client.get("/api/cards").json()
    assert _add(client, _entry(quantity=2), _entry(language="DE", quantity=1)).status_code == 200
    after = client.get("/api/cards").json()

    assert after["total_copies"] == before["total_copies"] + 3
    assert after["total_cards"] == before["total_cards"] + 1


# --- the file on disk --------------------------------------------------------


def test_a_save_writes_a_new_export_and_touches_no_existing_one(client, tmp_path):
    data = tmp_path / "data"
    assert _add(client, _entry()).status_code == 200
    written = sorted(data.glob("ygo_collection_*.csv"))
    assert len(written) == 1

    assert _add(client, _entry(language="IT")).status_code == 200
    after = sorted(data.glob("ygo_collection_*.csv"))
    assert len(after) == 2
    # The first save is still on disk, byte for byte: deleting the newest undoes.
    assert after[0].read_bytes() == written[0].read_bytes()
    assert client.get("/api/collection/status").json()["csv_path"] == str(after[-1])


def test_the_written_export_loads_as_a_collection(client, tmp_path):
    assert _add(client, _entry(), _entry(language="DE")).status_code == 200
    written = sorted((tmp_path / "data").glob("ygo_collection_*.csv"))[-1]
    with open_collection(written) as con:
        assert con.execute("SELECT COUNT(*) FROM collection").fetchone()[0] == 10


def test_leading_zeros_survive_a_hand_entered_passcode(client, tmp_path):
    assert _add(client, _entry(passcode="00004041", name="Mystical Elf")).status_code == 200
    written = sorted((tmp_path / "data").glob("ygo_collection_*.csv"))[-1]
    assert "00004041," in written.read_text(encoding="utf-8")
    # And it still joins to the catalogue, which knows the card as 4041.
    assert client.get("/api/cards/00004041").json()["in_catalogue"] is True


def test_the_first_card_of_a_collection_with_no_export_yet(empty_client, tmp_path):
    assert empty_client.get("/api/collection/status").json()["has_collection"] is False

    assert _add(empty_client, _entry(), _entry(language="DE")).status_code == 200

    status = empty_client.get("/api/collection/status").json()
    assert status["has_collection"] is True
    assert status["collection_rows"] == 2
    assert len(list((tmp_path / "data").glob("ygo_collection_*.csv"))) == 1


# --- rejections --------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"quantity": 0},
        {"quantity": -1},
        {"condition": "PRISTINE"},
        {"edition": "SECOND"},
        {"passcode": "not-a-number"},
        {"passcode": "123456789"},  # nine digits
        {"passcode": ""},
        {"name": ""},
        {"language": ""},
    ],
)
def test_a_row_that_breaks_the_contract_is_refused(client, bad):
    before = client.get("/api/cards").json()["total_copies"]
    assert _add(client, _entry(**bad)).status_code == 422
    assert client.get("/api/cards").json()["total_copies"] == before


def test_a_save_with_no_rows_is_refused(client):
    assert client.post("/api/collection/entries", json={"rows": []}).status_code == 422


def test_one_bad_row_rejects_the_whole_save(client):
    """Half a save would be worse than none: the caller cannot tell which half."""
    before = client.get("/api/cards").json()["total_copies"]
    assert _add(client, _entry(), _entry(condition="MINTY")).status_code == 422
    assert client.get("/api/cards").json()["total_copies"] == before


def test_language_is_free_form_but_normalized(client):
    """The column is unlisted by contract; an unknown code must still store."""
    assert _add(client, _entry(language=" zz ")).status_code == 200
    assert _owned(client, "85087012")[0]["language"] == "ZZ"


def test_a_failed_write_leaves_the_previous_collection_loaded(client, tmp_path, monkeypatch):
    before = client.get("/api/collection/status").json()

    def explode(*args, **kwargs):
        raise RuntimeError("disk gave up")

    monkeypatch.setattr("ygo_explorer.api.routes.collection.merge_to_csv", explode)
    assert _add(client, _entry()).status_code == 422

    assert client.get("/api/collection/status").json() == before
    assert not list((tmp_path / "data").glob("ygo_collection_*.csv"))


# --- the card picker ---------------------------------------------------------


def test_searching_by_name_folds_accents(client):
    hits = client.get("/api/catalogue/cards", params={"q": "necrovalley"}).json()
    assert [h["name"] for h in hits] == ["Nécrovalley"]
    assert hits[0]["passcode"] == "47355498"


def test_searching_matches_a_substring_and_ranks_the_exact_name_first(client):
    hits = client.get("/api/catalogue/cards", params={"q": "Dark Magician"}).json()
    assert hits[0]["name"] == "Dark Magician"


def test_searching_by_passcode_ignores_leading_zeros(client):
    for query in ("4041", "00004041"):
        hits = client.get("/api/catalogue/cards", params={"q": query}).json()
        assert [h["name"] for h in hits] == ["Mystical Elf"]


def test_the_picker_reports_what_is_already_owned_and_how_many_printings(client):
    (hit,) = client.get("/api/catalogue/cards", params={"q": "Dark Magician"}).json()[:1]
    assert hit["owned_copies"] == 6  # 4 unlisted + 2 SDY-006
    assert hit["printing_count"] == 2


def test_the_picker_offers_cards_the_collection_does_not_hold(client):
    (hit,) = client.get("/api/catalogue/cards", params={"q": "Nibiru"}).json()
    assert hit["owned_copies"] == 2
    assert client.get("/api/catalogue/cards", params={"q": "Virtual World"}).json()


def test_an_alternate_artwork_appears_once_by_name_but_is_findable_by_its_passcode(client):
    by_name = client.get("/api/catalogue/cards", params={"q": "Dark Magician"}).json()
    assert len(by_name) == 1

    by_alt = client.get("/api/catalogue/cards", params={"q": "46986421"}).json()
    assert [h["passcode"] for h in by_alt] == ["46986421"]
    # And it reports the copies of the *card*, not zero because they were logged
    # under the base id.
    assert by_alt[0]["owned_copies"] == 6


# --- searching in Italian ------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "localized"),
    [
        ("Mago Nero", "Mago Nero"),
        ("mago", "Mago Nero"),
        ("Primordiale", "Nibiru, l'Essere Primordiale"),
        ("Mondo Virtuale", "Hime Mondo Virtuale - Nyannyan"),
    ],
)
def test_a_card_is_findable_by_its_italian_name(client, query, localized):
    hits = client.get("/api/catalogue/cards", params={"q": query}).json()
    assert len(hits) == 1
    # The English name is what comes back, because that is what gets written to
    # the ledger; the localized one says why this card matched.
    assert hits[0]["matched_name"] == localized
    assert hits[0]["matched_language"] == "IT"


def test_a_localized_search_still_returns_the_english_name_to_store(client):
    (hit,) = client.get("/api/catalogue/cards", params={"q": "Mago Nero"}).json()
    assert hit["name"] == "Dark Magician"
    assert hit["passcode"] == "46986414"


def test_an_english_match_reports_no_localized_name(client):
    (hit,) = client.get("/api/catalogue/cards", params={"q": "Dark Magician"}).json()
    assert hit["matched_name"] is None
    assert hit["matched_language"] is None


def test_when_the_english_name_also_matches_nothing_extra_is_reported(client):
    """Italian 'Necrovalle' is a substring of English 'Nécrovalley'.

    Both rows match, and the English one wins — there is nothing to explain to
    someone who is already looking at a name containing what they typed.
    """
    (hit,) = client.get("/api/catalogue/cards", params={"q": "Necrovalle"}).json()
    assert hit["name"] == "Nécrovalley"
    assert hit["matched_name"] is None


def test_a_localized_name_is_folded_like_an_english_one(client):
    """Necrovalle has no accent, Nécrovalley does; both fold to the same thing."""
    assert client.get("/api/catalogue/cards", params={"q": "nécrovalle"}).json()
    assert client.get("/api/catalogue/cards", params={"q": "NECROVALLE"}).json()


def test_a_card_with_no_localized_name_is_still_found_in_english(client):
    """Mystical Elf is not in the Italian dump — an unscoped search must find it."""
    assert [
        h["name"] for h in client.get("/api/catalogue/cards", params={"q": "Mystical"}).json()
    ] == ["Mystical Elf"]


def test_one_card_matching_in_two_languages_appears_once(client):
    """'Nyannyan' is in the Italian name and the English one alike."""
    hits = client.get("/api/catalogue/cards", params={"q": "Nyannyan"}).json()
    assert len(hits) == 1
    assert hits[0]["name"] == "Virtual World Hime - Nyannyan"


# --- scoping the search to one language ----------------------------------------


def test_a_scoped_search_finds_a_card_by_that_languages_name(client):
    hits = client.get(
        "/api/catalogue/cards", params={"q": "Mago Nero", "language": "IT"}
    ).json()
    assert [h["name"] for h in hits] == ["Dark Magician"]
    assert hits[0]["matched_name"] == "Mago Nero"
    assert hits[0]["matched_language"] == "IT"


def test_a_scoped_search_does_not_match_another_languages_name(client):
    """The whole point of the scope: Italian means Italian, not Italian-or-English."""
    assert (
        client.get(
            "/api/catalogue/cards", params={"q": "Dark Magician", "language": "IT"}
        ).json()
        == []
    )


def test_a_scoped_search_hides_a_card_the_localized_dump_does_not_cover(client):
    """Mystical Elf has no Italian name, so it is not findable while IT is chosen."""
    assert (
        client.get("/api/catalogue/cards", params={"q": "Mystical", "language": "IT"}).json()
        == []
    )


def test_scoping_to_english_excludes_the_localized_names(client):
    assert (
        client.get(
            "/api/catalogue/cards", params={"q": "Mago Nero", "language": "EN"}
        ).json()
        == []
    )
    assert [
        h["name"]
        for h in client.get(
            "/api/catalogue/cards", params={"q": "Dark Magician", "language": "EN"}
        ).json()
    ] == ["Dark Magician"]


def test_a_passcode_resolves_whatever_language_is_chosen(client):
    """A passcode is a number, not a name — the scope has nothing to say about it."""
    for language in (None, "EN", "IT"):
        params = {"q": "46986414"} | ({"language": language} if language else {})
        assert [
            h["name"] for h in client.get("/api/catalogue/cards", params=params).json()
        ] == ["Dark Magician"]


def test_an_unknown_language_matches_nothing_rather_than_erroring(client):
    response = client.get("/api/catalogue/cards", params={"q": "Mago", "language": "FR"})
    assert response.status_code == 200
    assert response.json() == []


def test_the_catalogue_status_names_the_languages_it_can_be_searched_in(client):
    """Nothing is cached in this test, so it reports none rather than guessing.

    ``search_languages`` is the configured set, and is reported whether or not a
    dump has been fetched — the difference between the two is what tells the
    picker to offer a language as unavailable instead of silently finding nothing.
    """
    status = client.get("/api/catalogue/status").json()
    assert status["languages"] == []
    assert status["search_languages"] == ["EN", "IT"]


def test_search_still_works_on_a_cache_with_no_names_table(
    fixture_csv, fixture_dump, tmp_path, monkeypatch
):
    """An upgrade from a cache written before localized names existed.

    The names table is seeded from the English names already in `cards`, so the
    picker degrades to English rather than finding nothing at all.
    """
    from conftest import build_catalogue, patch_catalogue_paths

    paths = build_catalogue(fixture_dump, tmp_path, localized=False)
    paths["CARD_NAMES_PARQUET"].unlink()
    patch_catalogue_paths(monkeypatch, paths)

    with TestClient(create_app(fixture_csv)) as old:
        assert [
            h["name"] for h in old.get("/api/catalogue/cards", params={"q": "Dark"}).json()
        ] == ["Dark Magician"]
        assert old.get("/api/catalogue/cards", params={"q": "Mago Nero"}).json() == []


def test_a_search_that_matches_nothing_is_an_empty_list_not_an_error(client):
    assert client.get("/api/catalogue/cards", params={"q": "zzzznope"}).json() == []


def test_like_wildcards_are_searched_for_literally(client):
    assert client.get("/api/catalogue/cards", params={"q": "%"}).json() == []
    assert client.get("/api/catalogue/cards", params={"q": "Dark_Magician"}).json() == []


def test_printings_come_back_with_the_owned_ones_flagged(client):
    printings = client.get("/api/catalogue/cards/46986414/printings").json()
    assert {p["set_code"] for p in printings} == {"SDY-006", "LOB-005"}
    assert [p["set_code"] for p in printings if p["owned"]] == ["SDY-006"]
    assert all("set_rarity" in p for p in printings)


def test_printings_are_reachable_by_an_alternate_artwork_passcode(client):
    """The number on the card is the one the user types."""
    assert client.get("/api/catalogue/cards/46986421/printings").json() == client.get(
        "/api/catalogue/cards/46986414/printings"
    ).json()


def test_a_card_with_no_printings_answers_with_an_empty_list(client):
    assert client.get("/api/catalogue/cards/1/printings").json() == []


def test_printings_for_an_unknown_passcode_are_a_404(client):
    assert client.get("/api/catalogue/cards/99999999/printings").status_code == 404


def test_the_picker_works_before_any_collection_exists(empty_client):
    """First run: searching for the first card must not need a loaded export."""
    assert empty_client.get("/api/catalogue/cards", params={"q": "dark"}).status_code == 200
