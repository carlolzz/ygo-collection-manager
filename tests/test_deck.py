"""Deck import: parsing, resolution, and the missing-cards comparison."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from ygo_explorer.config import DEFAULT_PRICE_CURRENCY
from ygo_explorer.deck.compare import DeckCard, analyze_deck
from ygo_explorer.deck.export import missing_by_zone, missing_text, missing_ydke
from ygo_explorer.deck.parse import ParseError, parse_deck
from ygo_explorer.deck.resolve import resolve_deck
from ygo_explorer.money import Money

_FIXTURES = Path(__file__).parent / "fixtures"
YDKE = (_FIXTURES / "deck_fixture.ydke.txt").read_text(encoding="utf-8").strip()
PLAINTEXT = (_FIXTURES / "deck_fixture.txt").read_text(encoding="utf-8")


# --- parsing -----------------------------------------------------------------


def test_ydke_decodes_to_the_right_zone_sizes():
    deck = parse_deck(YDKE)
    assert deck.source_format == "ydke"
    assert deck.zone_counts() == {"main": 10, "extra": 2, "side": 3}


def test_ydke_repeats_become_copies():
    deck = parse_deck(YDKE)
    dark_magician = next(
        e for e in deck.entries if e.passcode == "46986414" and e.zone == "main"
    )
    assert dark_magician.quantity == 3


def test_plaintext_reads_quantities_and_zones():
    deck = parse_deck(PLAINTEXT)
    assert deck.source_format == "plaintext"
    assert deck.zone_counts() == {"main": 10, "extra": 2, "side": 3}


@pytest.mark.parametrize(
    "name",
    ["Nibiru, the Primal Being", "=Test Formula Card", "Necrovalley"],
)
def test_plaintext_handles_awkward_names(name):
    """A comma, a leading '=' and a hyphen are all legitimate inside a name."""
    deck = parse_deck(PLAINTEXT)
    assert any(e.name == name for e in deck.entries)


def test_a_name_containing_quotes_parses_intact():
    deck = parse_deck('Main Deck:\n2 Maxx "C"\n')
    assert deck.entries[0].name == 'Maxx "C"'
    assert deck.entries[0].quantity == 2


def test_ydk_format_with_bare_passcodes():
    deck = parse_deck("#created by test\n#main\n46986414\n46986414\n#extra\n8736823\n!side\n1\n")
    assert deck.source_format == "ydk"
    assert deck.zone_counts() == {"main": 2, "extra": 1, "side": 1}


@pytest.mark.parametrize("line", ["3x Dark Magician", "3 x Dark Magician", "3 Dark Magician"])
def test_quantity_notations(line):
    deck = parse_deck(f"Main Deck:\n{line}\n")
    assert deck.entries[0].quantity == 3
    assert deck.entries[0].name == "Dark Magician"


def test_a_bare_name_is_one_copy():
    deck = parse_deck("Main Deck:\nDark Magician\n")
    assert deck.entries[0].quantity == 1


@pytest.mark.parametrize("text", ["", "   \n\n  "])
def test_empty_input_raises(text):
    with pytest.raises(ParseError, match="empty"):
        parse_deck(text)


def test_a_malformed_ydke_raises_rather_than_guessing():
    with pytest.raises(ParseError):
        parse_deck("ydke://not-base64!!!")


def test_a_ydke_with_too_few_sections_raises():
    with pytest.raises(ParseError, match="three"):
        parse_deck("ydke://rvTMAg==!")


# --- resolution --------------------------------------------------------------


def test_every_line_of_both_fixtures_resolves(catalogue_con):
    for text in (YDKE, PLAINTEXT):
        resolution = resolve_deck(catalogue_con, parse_deck(text))
        assert resolution.unresolved == [], f"unresolved in {text[:20]}"


def test_an_alternate_art_passcode_resolves_to_its_card(catalogue_con):
    """The side deck's 46986421 is an alt art of Dark Magician 46986414."""
    resolution = resolve_deck(catalogue_con, parse_deck(YDKE))
    side = [e for e in resolution.resolved if e.zone == "side" and e.card_id == "46986414"]
    assert side and side[0].name == "Dark Magician"


def test_an_unknown_name_is_reported_not_dropped(catalogue_con):
    deck = parse_deck("Main Deck:\n3 Dark Magician\n2 Not A Real Card At All\n")
    resolution = resolve_deck(catalogue_con, deck)
    assert resolution.unresolved_labels == ["Not A Real Card At All"]
    assert len(resolution.resolved) == 1


def test_name_resolution_ignores_accents_and_case(catalogue_con):
    deck = parse_deck("Main Deck:\n1 nécrovalley\n")
    resolution = resolve_deck(catalogue_con, deck)
    assert resolution.resolved[0].name == "Nécrovalley"


def test_a_deck_passcode_matches_a_leading_zero_collection_passcode(catalogue_con):
    """The deck says 4041; the ledger says 00004041. Same card."""
    resolution = resolve_deck(catalogue_con, parse_deck(YDKE))
    assert any(e.card_id == "4041" for e in resolution.resolved)


# --- comparison --------------------------------------------------------------


def test_the_two_fixture_formats_describe_the_same_deck(catalogue_con):
    """Same list, two exports. If these disagree, one parser is wrong."""
    a = analyze_deck(catalogue_con, parse_deck(YDKE))
    b = analyze_deck(catalogue_con, parse_deck(PLAINTEXT))
    assert (a.total_needed, a.total_owned, a.total_missing) == (
        b.total_needed,
        b.total_owned,
        b.total_missing,
    )
    assert a.estimated_cost == b.estimated_cost
    assert {c.card_id: c.missing for c in a.cards} == {c.card_id: c.missing for c in b.cards}


def test_demand_is_aggregated_across_zones(catalogue_con):
    """3 Dark Magician in the main and 1 in the side needs four physical cards."""
    analysis = analyze_deck(catalogue_con, parse_deck(YDKE))
    dm = next(c for c in analysis.cards if c.card_id == "46986414")
    assert dm.zones == {"main": 3, "extra": 0, "side": 1}
    assert dm.needed == 4


def test_ownership_counts_every_copy_regardless_of_printing_or_condition(catalogue_con):
    """The fixture owns 4 NEAR_MINT with no printing and 2 POOR from SDY-006."""
    analysis = analyze_deck(catalogue_con, parse_deck(YDKE))
    dm = next(c for c in analysis.cards if c.card_id == "46986414")
    assert dm.owned == 6
    assert dm.missing == 0, "owning six covers a need of four"


def test_a_shortfall_is_the_difference(catalogue_con):
    analysis = analyze_deck(catalogue_con, parse_deck(YDKE))
    elf = next(c for c in analysis.cards if c.card_id == "4041")
    assert (elf.needed, elf.owned, elf.missing) == (2, 1, 1)


def test_spare_copies_do_not_count_as_progress(catalogue_con):
    """Owning six Dark Magicians for a four-of contributes four, not six."""
    analysis = analyze_deck(catalogue_con, parse_deck(YDKE))
    assert analysis.total_owned <= analysis.total_needed


def test_totals_add_up(catalogue_con):
    analysis = analyze_deck(catalogue_con, parse_deck(YDKE))
    assert analysis.total_needed == 15
    assert analysis.total_owned + analysis.total_missing == analysis.total_needed


def test_cost_uses_the_per_passcode_market_low_not_the_printing_price(catalogue_con):
    """Buying a playable copy, so the market low — not SDY-006's $9.96.

    Pinned to USD: SDY-006 is the only printing-grain price in the fixture, and
    printing prices exist in no other currency.
    """
    analysis = analyze_deck(
        catalogue_con,
        parse_deck("Main Deck:\n9 Dark Magician\n"),
        source_field="tcgplayer_price",
    )
    dm = next(c for c in analysis.cards if c.card_id == "46986414")
    assert dm.missing == 3
    assert dm.unit_price == Money(Decimal("1.24"), "USD")
    assert dm.subtotal == Money(Decimal("3.72"), "USD")


def test_no_condition_multiplier_is_applied_to_a_purchase(catalogue_con):
    """You buy near mint; the POOR copies you own do not discount the shopping list."""
    analysis = analyze_deck(catalogue_con, parse_deck("Main Deck:\n9 Dark Magician\n"))
    dm = next(c for c in analysis.cards if c.card_id == "46986414")
    assert dm.subtotal.amount == dm.unit_price.amount * 3


def test_an_unpriceable_missing_card_is_counted_separately(catalogue_con):
    """The fixture's =Test Formula Card has only 0.00 prices, i.e. none.

    The deck needs 2 and the ledger owns 1, so one is missing and unpriceable.
    """
    analysis = analyze_deck(catalogue_con, parse_deck(YDKE))
    formula = next(c for c in analysis.cards if c.card_id == "1")
    assert (formula.needed, formula.owned, formula.missing) == (2, 1, 1)
    assert formula.unit_price is None
    assert analysis.unpriced_missing_cards >= 1
    assert "no price" in analysis.caveat


def test_the_estimate_states_its_currency_and_basis(catalogue_con):
    """The default run, and therefore the configured currency."""
    analysis = analyze_deck(catalogue_con, parse_deck(YDKE))
    assert analysis.currency == DEFAULT_PRICE_CURRENCY
    assert analysis.estimated_cost.currency == DEFAULT_PRICE_CURRENCY
    assert f"Estimate in {DEFAULT_PRICE_CURRENCY}" in analysis.caveat
    assert "playable copy" in analysis.caveat


def test_the_price_field_chooses_the_currency(catalogue_con):
    """Nothing is converted: asking for another field asks for another currency."""
    analysis = analyze_deck(
        catalogue_con, parse_deck(YDKE), source_field="tcgplayer_price"
    )
    assert analysis.currency == "USD"
    assert analysis.estimated_cost.currency == "USD"


def test_the_cost_is_the_sum_of_the_subtotals(catalogue_con):
    analysis = analyze_deck(catalogue_con, parse_deck(YDKE))
    expected = sum(
        (c.subtotal.amount for c in analysis.cards if c.subtotal), start=Decimal("0")
    )
    assert analysis.estimated_cost.amount == expected


def test_owning_nothing_means_the_whole_deck_is_missing(catalogue_con):
    """Nibiru is in the catalogue but the fixture ledger holds only two."""
    analysis = analyze_deck(
        catalogue_con, parse_deck("Main Deck:\n3 Dark Magician\n3 Nibiru, the Primal Being\n")
    )
    nibiru = next(c for c in analysis.cards if c.card_id == "27204311")
    assert (nibiru.needed, nibiru.owned, nibiru.missing) == (3, 2, 1)


# --- exporting the shortfall --------------------------------------------------


def _card(passcode, name, zones, owned):
    needed = sum(zones.values())
    return DeckCard(
        card_id=passcode,
        passcode=passcode,
        name=name,
        needed=needed,
        owned=owned,
        missing=max(0, needed - owned),
        zones={"main": 0, "extra": 0, "side": 0} | zones,
        unit_price=None,
        subtotal=None,
    )


def test_owned_copies_are_spent_main_first():
    """2 main + 1 side with one owned is short one main and one side."""
    assert missing_by_zone({"main": 2, "extra": 0, "side": 1}, 1) == {
        "main": 1,
        "extra": 0,
        "side": 1,
    }


def test_the_zone_shortfalls_sum_to_the_missing_count():
    card = _card("46986414", "Dark Magician", {"main": 3, "side": 1}, owned=1)
    assert sum(missing_by_zone(card.zones, card.owned).values()) == card.missing


def test_spare_copies_do_not_make_a_zone_negative():
    assert missing_by_zone({"main": 1, "extra": 0, "side": 0}, 9) == {
        "main": 0,
        "extra": 0,
        "side": 0,
    }


def test_the_exported_ydke_reads_back_as_the_shortfall():
    cards = [
        _card("46986414", "Dark Magician", {"main": 3, "side": 1}, owned=1),
        _card("8736823", "Test Fusion", {"extra": 2}, owned=0),
    ]
    deck = parse_deck(missing_ydke(cards))
    assert deck.source_format == "ydke"
    assert deck.zone_counts() == {"main": 2, "extra": 2, "side": 1}


def test_the_exported_list_reads_back_as_the_shortfall():
    cards = [
        _card("46986414", "Dark Magician", {"main": 3, "side": 1}, owned=1),
        _card("8736823", "Test Fusion", {"extra": 2}, owned=0),
    ]
    deck = parse_deck(missing_text(cards))
    assert deck.source_format == "plaintext"
    assert deck.zone_counts() == {"main": 2, "extra": 2, "side": 1}
    assert {(e.zone, e.name, e.quantity) for e in deck.entries} == {
        ("main", "Dark Magician", 2),
        ("extra", "Test Fusion", 2),
        ("side", "Dark Magician", 1),
    }


def test_a_zone_with_nothing_missing_gets_no_heading():
    text = missing_text([_card("4041", "Mystical Elf", {"main": 2}, owned=1)])
    assert text == "Main Deck:\n1 Mystical Elf"


def test_the_list_is_alphabetical_within_a_zone():
    cards = [
        _card("2", "Zombie Warrior", {"main": 1}, owned=0),
        _card("3", "aardvark token", {"main": 1}, owned=0),
        _card("4", "Mystical Elf", {"main": 3}, owned=0),
    ]
    names = [line.split(" ", 1)[1] for line in missing_text(cards).splitlines()[1:]]
    assert names == ["aardvark token", "Mystical Elf", "Zombie Warrior"]


def test_a_fully_owned_deck_exports_nothing():
    cards = [_card("46986414", "Dark Magician", {"main": 3}, owned=6)]
    assert missing_ydke(cards) == ""
    assert missing_text(cards) == ""


def test_a_passcode_ydke_cannot_carry_still_reaches_the_list():
    """One unencodable passcode should not cost the user the whole code."""
    cards = [
        _card("not-a-passcode", "Odd One Out", {"main": 1}, owned=0),
        _card("4041", "Mystical Elf", {"main": 1}, owned=0),
    ]
    assert parse_deck(missing_ydke(cards)).zone_counts() == {"main": 1, "extra": 0, "side": 0}
    assert "Odd One Out" in missing_text(cards)


def test_a_real_analysis_round_trips_to_the_same_shortfall(catalogue_con):
    """The exported list, fed back in, reports needing exactly what was missing."""
    analysis = analyze_deck(catalogue_con, parse_deck(YDKE))
    again = analyze_deck(catalogue_con, parse_deck(missing_text(analysis.cards)))
    assert again.total_needed == analysis.total_missing
