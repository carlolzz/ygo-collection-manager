from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Set before anything imports ygo_explorer.config, which reads these once.
# Keeps the suite off the network and out of the real cache directory.
_SANDBOX = Path(tempfile.mkdtemp(prefix="ygo-tests-"))
os.environ.setdefault("YGO_DATA_DIR", str(_SANDBOX))
os.environ.setdefault("YGO_CACHE_DIR", str(_SANDBOX / "cache"))
os.environ["YGO_WARM_IMAGES"] = "0"

import pytest  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_CSV = FIXTURES / "collection_fixture.csv"
FIXTURE_DUMP = FIXTURES / "cardinfo_fixture.json"
FIXTURE_DUMPS_LOCALIZED = {
    "DE": FIXTURES / "cardinfo_fixture.de.json",
    "IT": FIXTURES / "cardinfo_fixture.it.json",
}
FIXTURE_YDKE = FIXTURES / "deck_fixture.ydke.txt"
FIXTURE_DECK_TEXT = FIXTURES / "deck_fixture.txt"

#: The parquet the catalogue is built from, by the config name each is bound to.
#: Kept in one place so a table added to the catalogue is added to every test's
#: wiring at once, rather than being silently left at its real-cache default.
CATALOGUE_PARQUET = {
    "CARDS_PARQUET": "cards.parquet",
    "CARD_SETS_PARQUET": "card_sets.parquet",
    "CARD_PRICES_PARQUET": "card_prices.parquet",
    "CARD_NAMES_PARQUET": "card_names.parquet",
}


def build_catalogue(dump_path: Path, out_dir: Path, *, localized: bool = True) -> dict:
    """Normalize the fixture dumps into ``out_dir``; return the paths by config name.

    Args:
        localized: include the German and Italian name indexes. False leaves the
            names table English-only, which is what a cache fetched before those
            languages were configured looks like.
    """
    import json as _json

    from ygo_explorer.catalogue.normalize import normalize_dump

    paths = {name: out_dir / filename for name, filename in CATALOGUE_PARQUET.items()}
    extra = (
        {
            language: _json.loads(path.read_text(encoding="utf-8"))["data"]
            for language, path in FIXTURE_DUMPS_LOCALIZED.items()
        }
        if localized
        else None
    )
    normalize_dump(
        _json.loads(dump_path.read_text(encoding="utf-8"))["data"],
        cards_path=paths["CARDS_PARQUET"],
        card_sets_path=paths["CARD_SETS_PARQUET"],
        card_prices_path=paths["CARD_PRICES_PARQUET"],
        card_names_path=paths["CARD_NAMES_PARQUET"],
        localized=extra,
    )
    return paths


def patch_catalogue_paths(monkeypatch, paths: dict) -> None:
    """Point the app's catalogue at ``paths`` without passing them through.

    The app under test is then wired exactly as it is in production, rather than
    through an argument only the tests use.
    """
    for name, path in paths.items():
        monkeypatch.setattr(f"ygo_explorer.catalogue.views.{name}", path)


@pytest.fixture
def fixture_csv() -> Path:
    return FIXTURE_CSV


@pytest.fixture
def fixture_dump() -> Path:
    return FIXTURE_DUMP


@pytest.fixture
def collection_con(fixture_csv: Path):
    from ygo_explorer.collection.loader import open_collection

    con = open_collection(fixture_csv)
    yield con
    con.close()


@pytest.fixture
def catalogue_con(fixture_csv: Path, fixture_dump: Path, tmp_path: Path):
    """Collection plus the fixture catalogue, on one connection."""
    from ygo_explorer.catalogue.views import attach_catalogue
    from ygo_explorer.collection.loader import open_collection

    paths = build_catalogue(fixture_dump, tmp_path)
    con = open_collection(fixture_csv)
    attach_catalogue(
        con,
        cards_path=paths["CARDS_PARQUET"],
        card_sets_path=paths["CARD_SETS_PARQUET"],
        card_prices_path=paths["CARD_PRICES_PARQUET"],
        card_names_path=paths["CARD_NAMES_PARQUET"],
    )
    yield con
    con.close()


@pytest.fixture
def store(tmp_path: Path):
    from ygo_explorer.pricing.snapshots import SnapshotStore

    s = SnapshotStore(tmp_path / "snapshots.parquet")
    yield s
    s.close()
