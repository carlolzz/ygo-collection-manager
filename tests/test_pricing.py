"""Money, condition multipliers, the snapshot store and valuation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from ygo_explorer.collection.schema import CONDITIONS
from ygo_explorer.config import DEFAULT_PRICE_CURRENCY, DEFAULT_PRICE_FIELD
from ygo_explorer.money import CurrencyMismatch, Money, sum_money
from ygo_explorer.pricing.conditions import (
    CONDITION_MULTIPLIERS,
    UnknownCondition,
    multiplier_for,
)
from ygo_explorer.pricing.provider import CredentialsRequired, PriceProvider
from ygo_explorer.pricing.snapshots import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    SnapshotStore,
)
from ygo_explorer.pricing.stubs import CardmarketProvider, TcgplayerProvider
from ygo_explorer.pricing.valuation import PER_PASSCODE, PER_PRINTING, value_rows
from ygo_explorer.pricing.ygoprodeck import CURRENCY_BY_FIELD, YgoprodeckProvider


# --- Money -------------------------------------------------------------------


def test_money_requires_a_currency():
    with pytest.raises(ValueError):
        Money(Decimal("1"), "")


def test_money_refuses_float():
    with pytest.raises(TypeError, match="Decimal"):
        Money(1.23, "USD")


def test_summing_two_currencies_raises_rather_than_coercing():
    with pytest.raises(CurrencyMismatch, match="implicit 1:1"):
        Money(Decimal("1.00"), "USD") + Money(Decimal("1.00"), "EUR")


def test_money_adds_within_a_currency():
    total = Money(Decimal("1.10"), "USD") + Money(Decimal("2.20"), "USD")
    assert total == Money(Decimal("3.30"), "USD")


def test_money_multiplication_rejects_float():
    with pytest.raises(TypeError, match="Decimal"):
        Money(Decimal("1.00"), "USD") * 0.65


def test_money_rounds_half_up_to_the_minor_unit():
    assert Money(Decimal("1.005"), "USD").rounded().amount == Decimal("1.01")


def test_sum_money_skips_the_unpriced():
    total = sum_money([Money(Decimal("2"), "USD"), None, Money(Decimal("3"), "USD")], "USD")
    assert total == Money(Decimal("5"), "USD")


def test_sum_money_of_nothing_is_zero_in_the_stated_currency():
    assert sum_money([], "EUR") == Money(Decimal("0"), "EUR")


def test_parse_keeps_precision_from_the_string_form():
    assert Money.parse("0.35", "EUR").amount == Decimal("0.35")
    assert Money.parse(None, "EUR") is None


# --- condition multipliers ---------------------------------------------------


def test_all_seven_grades_have_a_multiplier():
    assert list(CONDITION_MULTIPLIERS) == list(CONDITIONS)


def test_near_mint_is_the_reference_grade():
    assert multiplier_for("NEAR_MINT") == Decimal("1.00")


def test_multipliers_decrease_from_best_to_worst():
    values = [CONDITION_MULTIPLIERS[c] for c in CONDITIONS]
    assert values == sorted(values, reverse=True)


def test_an_unknown_grade_is_an_error_not_a_silent_one():
    with pytest.raises(UnknownCondition, match="PRISTINE"):
        multiplier_for("PRISTINE")


def test_there_is_no_edition_multiplier():
    """Edition moves price in reality, but is deliberately left unmodelled."""
    import ygo_explorer.pricing.conditions as module

    assert not hasattr(module, "EDITION_MULTIPLIERS")


# --- the snapshot store ------------------------------------------------------


def _record(store, key, amount, status=STATUS_OK, **kw):
    store.record(
        key,
        provider="ygoprodeck",
        currency="USD",
        source_field="tcgplayer_price",
        amount=amount,
        status=status,
        **kw,
    )


def test_snapshots_are_append_only(store):
    key = ("46986414", "SDY-006")
    _record(store, key, Decimal("1.00"))
    _record(store, key, Decimal("2.00"))
    assert store.count() == 2, "a refetch appends; history is the point"


def test_latest_returns_the_newest_row_per_key(store):
    key = ("46986414", "SDY-006")
    old = datetime.now(timezone.utc) - timedelta(days=3)
    _record(store, key, Decimal("1.00"), fetched_at=old)
    _record(store, key, Decimal("2.00"))
    latest = store.latest("ygoprodeck", "tcgplayer_price")
    assert latest[key].amount == Decimal("2.00")


def test_failures_are_recorded_so_a_resume_knows_it_tried(store):
    _record(store, ("1", "TST-EN001"), None, status=STATUS_ERROR, detail="HTTP 503")
    snap = store.latest("ygoprodeck", "tcgplayer_price")[("1", "TST-EN001")]
    assert snap.status == STATUS_ERROR
    assert snap.money is None
    assert snap.detail == "HTTP 503"


def test_fresh_keys_include_failures(store):
    """A source that has already said 'no price' must not be asked again."""
    _record(store, ("1", "TST-EN001"), None, status=STATUS_UNAVAILABLE)
    fresh = store.fresh_keys("ygoprodeck", "tcgplayer_price")
    assert ("1", "TST-EN001") in fresh


def test_stale_keys_are_not_reused(store):
    long_ago = datetime.now(timezone.utc) - timedelta(days=60)
    _record(store, ("1", "TST-EN001"), Decimal("1.00"), fetched_at=long_ago)
    assert store.fresh_keys("ygoprodeck", "tcgplayer_price", max_age_days=14) == set()


def test_snapshots_survive_a_reopen(store, tmp_path):
    _record(store, ("46986414", None), Decimal("1.24"))
    store.flush()
    reopened = SnapshotStore(store.path)
    try:
        assert reopened.count() == 1
        assert reopened.latest("ygoprodeck", "tcgplayer_price")[
            ("46986414", None)
        ].money == Money(Decimal("1.24"), "USD")
    finally:
        reopened.close()


def test_a_null_set_code_is_a_valid_key(store):
    _record(store, ("46986414", None), Decimal("1.24"))
    assert ("46986414", None) in store.latest("ygoprodeck", "tcgplayer_price")


# --- providers ---------------------------------------------------------------


def test_every_price_field_declares_a_currency():
    assert CURRENCY_BY_FIELD["cardmarket_price"] == "EUR"
    assert all(
        CURRENCY_BY_FIELD[f] == "USD"
        for f in ("tcgplayer_price", "ebay_price", "amazon_price", "coolstuffinc_price")
    )


def test_provider_rejects_an_unknown_field(catalogue_con):
    with pytest.raises(ValueError, match="Unknown price field"):
        YgoprodeckProvider(catalogue_con, "made_up_price")


def test_ygoprodeck_provider_satisfies_the_protocol(catalogue_con):
    assert isinstance(YgoprodeckProvider(catalogue_con), PriceProvider)


def test_batch_prices_answer_in_one_call(catalogue_con):
    provider = YgoprodeckProvider(catalogue_con, "tcgplayer_price")
    keys = [("46986414", "SDY-006"), ("46986414", None), ("99999999", None)]
    prices = provider.prices(keys)
    assert prices[("46986414", "SDY-006")] == Money(Decimal("9.96"), "USD")
    assert prices[("46986414", None)] == Money(Decimal("1.24"), "USD")
    assert prices[("99999999", None)] is None, "not in the dump, so no price"


def test_a_eur_run_gets_no_printing_prices(catalogue_con):
    """set_price is USD on every path, so EUR cannot be refined per printing."""
    provider = YgoprodeckProvider(catalogue_con, "cardmarket_price")
    assert provider.currency == "EUR"
    assert provider.printing_prices() == {}


@pytest.mark.parametrize("provider", [CardmarketProvider(), TcgplayerProvider()])
def test_credential_gated_providers_say_so_clearly(provider):
    with pytest.raises(CredentialsRequired, match="credentials"):
        provider.price("46986414")
    with pytest.raises(CredentialsRequired):
        provider.prices([("46986414", None)])


@pytest.mark.parametrize("provider", [CardmarketProvider(), TcgplayerProvider()])
def test_stubs_still_satisfy_the_protocol(provider):
    assert isinstance(provider, PriceProvider)


# --- valuation ---------------------------------------------------------------


def test_valuation_defaults_to_the_configured_field_and_its_currency(
    catalogue_con, store
):
    result = value_rows(catalogue_con, store)
    assert result.source_field == DEFAULT_PRICE_FIELD
    assert result.currency == DEFAULT_PRICE_CURRENCY
    assert result.total.currency == DEFAULT_PRICE_CURRENCY


def test_valuation_totals_in_one_stated_currency(catalogue_con, store):
    """The field picks the currency; nothing is ever converted into it."""
    result = value_rows(catalogue_con, store, source_field="tcgplayer_price")
    assert result.currency == "USD"
    assert result.total.currency == "USD"
    assert result.source_field == "tcgplayer_price"


def test_valuation_reports_the_pricing_basis_split(catalogue_con, store):
    # Pinned to USD: the per-printing basis exists in no other currency.
    result = value_rows(catalogue_con, store, source_field="tcgplayer_price")
    assert result.per_printing_rows + result.per_passcode_rows + result.unpriced_rows == 8
    assert result.per_printing_rows >= 1
    assert result.unpriced_rows >= 1, "the fixture's unlisted promo cannot be priced"


def test_the_row_without_a_printing_is_valued_not_excluded(catalogue_con, store):
    result = value_rows(catalogue_con, store)
    no_printing = [r for r in result.rows if r.passcode == "46986414" and r.set_code is None]
    assert len(no_printing) == 1
    assert no_printing[0].basis == PER_PASSCODE
    assert no_printing[0].subtotal is not None, "no set_code is not an error"


def test_a_known_printing_beats_the_per_passcode_price(catalogue_con, store):
    result = value_rows(catalogue_con, store, source_field="tcgplayer_price")
    row = next(r for r in result.rows if r.set_code == "SDY-006")
    assert row.basis == PER_PRINTING
    assert row.unit_price == Money(Decimal("9.96"), "USD")


def test_condition_and_quantity_are_both_applied(catalogue_con, store):
    result = value_rows(catalogue_con, store, source_field="tcgplayer_price")
    row = next(r for r in result.rows if r.set_code == "SDY-006")
    # 9.96 * 0.40 (POOR) * 2 copies
    assert row.multiplier == Decimal("0.40")
    assert row.quantity == 2
    assert row.subtotal == Money(Decimal("7.97"), "USD")


def test_an_unpriceable_row_contributes_nothing_but_is_counted(catalogue_con, store):
    result = value_rows(catalogue_con, store)
    row = next(r for r in result.rows if r.passcode == "99999999")
    assert row.subtotal is None
    assert result.unpriced_copies >= 1


def test_the_total_is_the_sum_of_the_subtotals(catalogue_con, store):
    result = value_rows(catalogue_con, store, source_field="tcgplayer_price")
    expected = sum_money((r.subtotal for r in result.rows), "USD").rounded()
    assert result.total == expected


def test_valuation_always_says_it_is_an_estimate(catalogue_con, store):
    result = value_rows(catalogue_con, store, source_field="tcgplayer_price")
    assert result.is_estimate is True
    assert "Estimate in USD" in result.caveat
    assert "rarity is not reflected" in result.caveat


def test_valuing_one_card_covers_only_its_rows(catalogue_con, store):
    result = value_rows(catalogue_con, store, passcode="46986414")
    assert {r.passcode for r in result.rows} == {"46986414"}
    assert len(result.rows) == 2


def test_every_price_read_lands_in_the_snapshot_store(catalogue_con, store):
    assert store.count() == 0
    value_rows(catalogue_con, store)
    assert store.count() == 8, "one snapshot per valued row, absences included"


def test_absences_are_snapshotted_too(catalogue_con, store):
    value_rows(catalogue_con, store, source_field="tcgplayer_price")
    latest = store.latest("ygoprodeck", "tcgplayer_price")
    assert latest[("99999999", None)].status == STATUS_UNAVAILABLE
