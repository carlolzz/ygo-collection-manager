"""Build step 2: the dump cache, the derived tables and the passcode join."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import polars as pl
import pytest

from ygo_explorer.catalogue.dump import (
    CachePaths,
    DumpMeta,
    fetch_dump,
    load_meta,
    read_dump,
)
from ygo_explorer.catalogue.normalize import (
    card_prices_frame,
    card_sets_frame,
    cards_frame,
    normalize_dump,
    passcode_key,
)
from ygo_explorer.catalogue.views import attach_catalogue
from ygo_explorer.collection.loader import open_collection


@pytest.fixture
def dump_cards(fixture_dump: Path) -> list[dict]:
    return json.loads(fixture_dump.read_text(encoding="utf-8"))["data"]


@pytest.fixture
def con(fixture_csv: Path, dump_cards: list[dict], tmp_path: Path):
    normalize_dump(
        dump_cards,
        cards_path=tmp_path / "cards.parquet",
        card_sets_path=tmp_path / "card_sets.parquet",
        card_prices_path=tmp_path / "card_prices.parquet",
    )
    connection = open_collection(fixture_csv)
    attach_catalogue(
        connection,
        cards_path=tmp_path / "cards.parquet",
        card_sets_path=tmp_path / "card_sets.parquet",
        card_prices_path=tmp_path / "card_prices.parquet",
    )
    yield connection
    connection.close()


# --- the canonical join key --------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("00004041", "4041"), ("4041", "4041"), ("00000001", "1"), ("0", "0"), (4041, "4041")],
)
def test_passcode_key_matches_the_sql_definition(raw, expected):
    assert passcode_key(raw) == expected


def test_python_and_sql_passcode_keys_agree(con):
    rows = con.execute("SELECT passcode, passcode_key FROM collection").fetchall()
    assert all(passcode_key(p) == k for p, k in rows)


# --- alternate-art passcodes -------------------------------------------------


def test_alternate_art_ids_get_their_own_catalogue_entry(dump_cards):
    frame = cards_frame(dump_cards)
    passcodes = set(frame["passcode"].to_list())
    assert "46986414" in passcodes
    assert "46986421" in passcodes, "alt-art id from card_images[] must be indexed"


def test_alternate_art_entry_points_back_at_the_same_card(dump_cards):
    row = cards_frame(dump_cards).filter(pl.col("passcode") == "46986421").to_dicts()[0]
    assert row["card_id"] == "46986414"
    assert row["name"] == "Dark Magician"
    assert row["is_alternate_art"] is True
    assert row["image_url"].endswith("46986421.jpg")


def test_the_canonical_id_is_not_flagged_as_alternate_art(dump_cards):
    row = cards_frame(dump_cards).filter(pl.col("passcode") == "46986414").to_dicts()[0]
    assert row["is_alternate_art"] is False


# --- the join ----------------------------------------------------------------


def test_leading_zero_passcode_still_matches_the_catalogue(con):
    name, type_, attribute = con.execute(
        "SELECT catalogue_name, type, attribute FROM collection_enriched "
        "WHERE passcode = '00004041'"
    ).fetchone()
    assert (name, type_, attribute) == ("Mystical Elf", "Normal Monster", "LIGHT")


def test_a_row_absent_from_the_dump_is_displayed_not_dropped(con):
    row = con.execute(
        "SELECT name, quantity, condition, type, in_catalogue FROM collection_enriched "
        "WHERE passcode = '99999999'"
    ).fetchone()
    assert row is not None, "an unmatched row must survive the join"
    name, quantity, condition, card_type, in_catalogue = row
    assert (name, quantity, condition) == ("Unlisted Promo Card", 1, "NEAR_MINT")
    assert card_type is None, "its card attributes are unknown, not invented"
    assert in_catalogue is False


def test_the_join_does_not_change_the_row_count(con):
    before = con.execute("SELECT COUNT(*) FROM collection").fetchone()[0]
    after = con.execute("SELECT COUNT(*) FROM collection_enriched").fetchone()[0]
    assert before == after == 8


def test_the_join_does_not_change_the_totals(con):
    total, distinct = con.execute(
        "SELECT SUM(quantity), COUNT(DISTINCT passcode) FROM collection_enriched"
    ).fetchone()
    assert (total, distinct) == (19, 7)


def test_catalogue_status_reports_coverage(con):
    row = con.execute(
        "SELECT collection_rows, matched_rows, unmatched_rows, unmatched_passcodes "
        "FROM catalogue_status"
    ).fetchone()
    assert row == (8, 7, 1, 1)


def test_collection_by_card_rolls_ownership_up_to_one_row_per_card(con):
    passcode, total_copies, row_count = con.execute(
        "SELECT passcode, total_copies, row_count FROM collection_by_card "
        "WHERE passcode = '46986414'"
    ).fetchone()
    assert (passcode, total_copies, row_count) == ("46986414", 6, 2)


def test_collection_by_card_has_one_row_per_distinct_passcode(con):
    cards, distinct = con.execute(
        "SELECT (SELECT COUNT(*) FROM collection_by_card), "
        "(SELECT COUNT(DISTINCT passcode) FROM collection)"
    ).fetchone()
    assert cards == distinct == 7


# --- printings and prices ----------------------------------------------------


def test_card_sets_carry_a_per_printing_price(con):
    rarity, price = con.execute(
        "SELECT set_rarity, set_price_usd FROM card_sets WHERE set_code = 'SDY-006'"
    ).fetchone()
    assert rarity == "Ultra Rare"
    assert str(price) == "9.96"


def test_prices_are_decimal_not_float(con):
    (column_type,) = con.execute(
        "SELECT column_type FROM (DESCRIBE card_prices) "
        "WHERE column_name = 'tcgplayer_price_usd'"
    ).fetchone()
    assert column_type == "DECIMAL(12,2)"


def test_each_price_column_names_its_own_currency(con):
    columns = {
        row[0] for row in con.execute("DESCRIBE card_prices").fetchall()
    } - {"card_id"}
    assert columns == {
        "cardmarket_price_eur",
        "tcgplayer_price_usd",
        "ebay_price_usd",
        "amazon_price_usd",
        "coolstuffinc_price_usd",
    }


def test_a_zero_price_reads_as_absent_not_as_free(con):
    row = con.execute(
        "SELECT tcgplayer_price_usd, cardmarket_price_eur FROM card_prices "
        "WHERE card_id = '1'"
    ).fetchone()
    assert row == (None, None)


def test_a_card_without_printings_yields_no_card_sets_rows(con):
    (count,) = con.execute(
        "SELECT COUNT(*) FROM card_sets WHERE card_id = '1'"
    ).fetchone()
    assert count == 0


def test_owned_printing_joins_to_its_catalogue_printing(con):
    """The refinement path: a set_code the ledger knows, priced at printing grain."""
    row = con.execute(
        """
        SELECT e.set_code, s.set_rarity, s.set_price_usd
        FROM collection_enriched e
        JOIN card_sets s ON s.card_id = e.card_id AND s.set_code = e.set_code
        WHERE e.passcode = '46986414' AND e.set_code = 'SDY-006'
        """
    ).fetchone()
    assert row[0] == "SDY-006"
    assert row[1] == "Ultra Rare"
    assert str(row[2]) == "9.96"


# --- working without a dump --------------------------------------------------


def test_everything_works_before_any_dump_is_fetched(fixture_csv, tmp_path):
    connection = open_collection(fixture_csv)
    attach_catalogue(
        connection,
        cards_path=tmp_path / "absent.parquet",
        card_sets_path=tmp_path / "absent_sets.parquet",
        card_prices_path=tmp_path / "absent_prices.parquet",
    )
    rows, matched = connection.execute(
        "SELECT collection_rows, matched_rows FROM catalogue_status"
    ).fetchone()
    assert (rows, matched) == (8, 0)
    assert connection.execute(
        "SELECT SUM(quantity) FROM collection_enriched"
    ).fetchone()[0] == 19
    connection.close()


# --- the dump client ---------------------------------------------------------


def _client(payload: bytes, recorder: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        return httpx.Response(200, content=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_fetch_dump_caches_the_json_and_derives_the_parquet(fixture_dump, tmp_path):
    payload = fixture_dump.read_bytes()
    requests: list[httpx.Request] = []
    paths = CachePaths(tmp_path)

    async with _client(payload, requests) as client:
        meta = await fetch_dump(client=client, cache_dir=tmp_path)

    assert meta.card_count == 6
    assert paths.dump.is_file() and paths.meta.is_file()
    assert paths.cards.is_file() and paths.card_sets.is_file()
    assert paths.card_prices.is_file()
    assert load_meta(paths.meta) == meta
    assert len(read_dump(paths.dump)) == 6
    # cardinfo.php returns everything only with zero parameters.
    assert requests[0].url.params == httpx.QueryParams()


@pytest.mark.asyncio
async def test_fetch_dump_leaves_an_existing_cache_alone(fixture_dump, tmp_path):
    payload = fixture_dump.read_bytes()
    requests: list[httpx.Request] = []

    async with _client(payload, requests) as client:
        await fetch_dump(client=client, cache_dir=tmp_path)
        await fetch_dump(client=client, cache_dir=tmp_path)

    assert len(requests) == 1, "a cached dump must not be re-downloaded implicitly"


@pytest.mark.asyncio
async def test_force_refetches(fixture_dump, tmp_path):
    payload = fixture_dump.read_bytes()
    requests: list[httpx.Request] = []

    async with _client(payload, requests) as client:
        await fetch_dump(client=client, cache_dir=tmp_path)
        await fetch_dump(client=client, cache_dir=tmp_path, force=True)

    assert len(requests) == 2


def test_dump_meta_reports_its_age():
    from datetime import datetime, timedelta, timezone

    then = datetime.now(timezone.utc) - timedelta(days=12)
    meta = DumpMeta(
        fetched_at=then.isoformat(), card_count=1, byte_size=1, source_url="x"
    )
    assert 11.9 < meta.age_days < 12.1


def test_read_dump_without_a_cache_says_how_to_get_one(tmp_path):
    with pytest.raises(FileNotFoundError, match="refresh-dump"):
        read_dump(tmp_path / "nothing.json")
