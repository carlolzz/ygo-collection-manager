"""Acceptance criteria for build step 1.

Each of the six criteria in the brief is asserted separately, so a regression
names itself rather than collapsing into one failing test.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ygo_explorer.collection.loader import (
    CollectionDataError,
    CollectionSchemaError,
    open_collection,
)
from ygo_explorer.collection.schema import COLLECTION_COLUMNS, CONDITIONS
from ygo_explorer.text import fold


def _rewrite_header(source: Path, target: Path, header: str) -> Path:
    body = source.read_bytes().split(b"\r\n", 1)[1]
    target.write_bytes(header.encode("utf-8") + b"\r\n" + body)
    return target


# --- 1. a missing or renamed column raises, naming the column ----------------


def test_missing_column_raises_naming_it(fixture_csv, tmp_path):
    dropped = ",".join(c for c in COLLECTION_COLUMNS if c != "rarity")
    bad = _rewrite_header(fixture_csv, tmp_path / "missing.csv", dropped)

    with pytest.raises(CollectionSchemaError) as excinfo:
        open_collection(bad)

    assert "rarity" in str(excinfo.value)


def test_renamed_column_raises_naming_both_names(fixture_csv, tmp_path):
    renamed = ",".join(
        "card_name" if c == "name" else c for c in COLLECTION_COLUMNS
    )
    bad = _rewrite_header(fixture_csv, tmp_path / "renamed.csv", renamed)

    with pytest.raises(CollectionSchemaError) as excinfo:
        open_collection(bad)

    message = str(excinfo.value)
    assert "name" in message and "card_name" in message


def test_reordered_columns_raise(fixture_csv, tmp_path):
    swapped = list(COLLECTION_COLUMNS)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    bad = _rewrite_header(fixture_csv, tmp_path / "reordered.csv", ",".join(swapped))

    with pytest.raises(CollectionSchemaError, match="order"):
        open_collection(bad)


def test_valid_header_is_accepted(collection_con):
    assert collection_con.execute("SELECT count(*) FROM collection").fetchone()[0] == 8


# --- 2. SUM(quantity) and COUNT(DISTINCT passcode), asserted separately ------


def test_total_copies_is_sum_of_quantity(collection_con):
    total = collection_con.execute("SELECT SUM(quantity) FROM collection").fetchone()[0]
    assert total == 19


def test_distinct_cards_is_count_distinct_passcode(collection_con):
    distinct = collection_con.execute(
        "SELECT COUNT(DISTINCT passcode) FROM collection"
    ).fetchone()[0]
    assert distinct == 7


def test_the_two_counts_differ_on_this_fixture(collection_con):
    total, distinct = collection_con.execute(
        "SELECT SUM(quantity), COUNT(DISTINCT passcode) FROM collection"
    ).fetchone()
    assert total != distinct, "fixture must exercise the difference, not hide it"


# --- 3. a leading-zero passcode survives as a string -------------------------


def test_leading_zero_passcode_is_preserved_as_string(collection_con):
    (passcode,) = collection_con.execute(
        "SELECT passcode FROM collection WHERE name = 'Mystical Elf'"
    ).fetchone()
    assert passcode == "00004041"
    assert isinstance(passcode, str)


def test_passcode_column_is_text_not_numeric(collection_con):
    (column_type,) = collection_con.execute(
        "SELECT column_type FROM (DESCRIBE collection) WHERE column_name = 'passcode'"
    ).fetchone()
    assert column_type == "VARCHAR"


def test_passcode_key_strips_leading_zeros_for_joining_only(collection_con):
    rows = collection_con.execute(
        "SELECT passcode, passcode_key FROM collection "
        "WHERE passcode IN ('00004041', '00000001', '8736823') ORDER BY passcode"
    ).fetchall()
    assert rows == [
        ("00000001", "1"),
        ("00004041", "4041"),
        ("8736823", "8736823"),
    ]


# --- 4. an empty set_code reads as NULL and is still counted -----------------


def test_empty_set_code_reads_as_null(collection_con):
    (nulls,) = collection_con.execute(
        "SELECT COUNT(*) FROM collection WHERE set_code IS NULL"
    ).fetchone()
    assert nulls == 2


def test_empty_set_name_and_rarity_read_as_null_too(collection_con):
    (nulls,) = collection_con.execute(
        "SELECT COUNT(*) FROM collection "
        "WHERE set_code IS NULL AND set_name IS NULL AND rarity IS NULL"
    ).fetchone()
    assert nulls == 2


def test_rows_without_a_printing_still_count_towards_totals(collection_con):
    (copies_without_printing,) = collection_con.execute(
        "SELECT SUM(quantity) FROM collection WHERE set_code IS NULL"
    ).fetchone()
    (total,) = collection_con.execute(
        "SELECT SUM(quantity) FROM collection"
    ).fetchone()
    assert copies_without_printing == 5
    assert total == 19, "the no-printing rows must be inside the total, not beside it"


def test_no_column_contains_an_empty_string_after_normalization(collection_con):
    for column in ("set_code", "set_name", "rarity", "notes"):
        (empties,) = collection_con.execute(
            f"SELECT COUNT(*) FROM collection WHERE {column} = ''"
        ).fetchone()
        assert empties == 0, f"{column} still holds '' instead of NULL"


# --- 5. a name beginning with ' loses exactly one apostrophe -----------------


def test_formula_guarded_name_loses_exactly_one_apostrophe(collection_con):
    (name,) = collection_con.execute(
        "SELECT name FROM collection WHERE passcode = '00000001'"
    ).fetchone()
    assert name == "=Test Formula Card"


def test_formula_guarded_notes_lose_exactly_one_apostrophe(collection_con):
    (notes,) = collection_con.execute(
        "SELECT notes FROM collection WHERE passcode = '00000001'"
    ).fetchone()
    assert notes == "-30% off"


def test_ordinary_names_are_left_alone(collection_con):
    names = [
        row[0]
        for row in collection_con.execute(
            "SELECT name FROM collection WHERE passcode <> '00000001'"
        ).fetchall()
    ]
    assert not any(n.startswith("'") for n in names)


def test_rfc4180_quoting_survives_the_read(collection_con):
    (name,) = collection_con.execute(
        "SELECT DISTINCT name FROM collection WHERE passcode = '27204311'"
    ).fetchone()
    assert name == 'Nibiru, the "Primal" Being'


# --- 6. created_at parses to the expected UTC instant ------------------------


def test_created_at_parses_to_the_expected_utc_instant(collection_con):
    (created_at,) = collection_con.execute(
        "SELECT created_at FROM collection WHERE passcode = '00004041'"
    ).fetchone()
    assert created_at == datetime(2026, 1, 2, 8, 0, 0, tzinfo=timezone.utc)


def test_timestamps_are_not_treated_as_epoch_milliseconds(collection_con):
    (created_at,) = collection_con.execute(
        "SELECT created_at FROM collection WHERE passcode = '99999999'"
    ).fetchone()
    assert created_at.year == 2026


def test_updated_at_can_differ_from_created_at(collection_con):
    created_at, updated_at = collection_con.execute(
        "SELECT created_at, updated_at FROM collection "
        "WHERE passcode = '46986414' AND condition = 'POOR'"
    ).fetchone()
    assert created_at == datetime(2026, 1, 4, 10, 15, 0, tzinfo=timezone.utc)
    assert updated_at == datetime(2026, 2, 1, 11, 0, 0, tzinfo=timezone.utc)


# --- diacritic folding -------------------------------------------------------


def test_fold_makes_accented_and_unaccented_names_equal():
    assert fold("Nécrovalley") == fold("Necrovalley") == "necrovalley"


def test_folded_name_column_is_searchable_without_accents(collection_con):
    (name,) = collection_con.execute(
        "SELECT name FROM collection WHERE name_folded = ?", [fold("necrovalley")]
    ).fetchone()
    assert name == "Nécrovalley"


# --- data validation ---------------------------------------------------------


def test_unknown_condition_is_an_error_not_a_silent_pass(fixture_csv, tmp_path):
    text = fixture_csv.read_text(encoding="utf-8")
    bad = tmp_path / "bad_condition.csv"
    bad.write_text(text.replace(",MINT,", ",PRISTINE,", 1), encoding="utf-8", newline="")

    with pytest.raises(CollectionDataError, match="PRISTINE"):
        open_collection(bad)


def test_quantity_below_one_is_an_error(fixture_csv, tmp_path):
    text = fixture_csv.read_text(encoding="utf-8")
    bad = tmp_path / "bad_quantity.csv"
    bad.write_text(text.replace(",EN,1,,2026-01-02", ",EN,0,,2026-01-02", 1),
                   encoding="utf-8", newline="")

    with pytest.raises(CollectionDataError, match="quantity"):
        open_collection(bad)


def test_unparseable_timestamp_is_an_error(fixture_csv, tmp_path):
    text = fixture_csv.read_text(encoding="utf-8")
    bad = tmp_path / "bad_timestamp.csv"
    bad.write_text(text.replace("2026-01-02T08:00:00.000Z", "1767340800000", 1),
                   encoding="utf-8", newline="")

    with pytest.raises(CollectionDataError, match="ISO-8601"):
        open_collection(bad)


def test_all_seven_conditions_are_represented_in_the_fixture(collection_con):
    present = {
        row[0]
        for row in collection_con.execute(
            "SELECT DISTINCT condition FROM collection"
        ).fetchall()
    }
    assert present == set(CONDITIONS)


# --- the export is never written to -------------------------------------------


def test_loading_does_not_modify_the_csv(fixture_csv, tmp_path):
    copy = tmp_path / "readonly.csv"
    copy.write_bytes(fixture_csv.read_bytes())
    before = copy.read_bytes()

    open_collection(copy).close()

    assert copy.read_bytes() == before
