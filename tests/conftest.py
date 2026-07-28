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
FIXTURE_YDKE = FIXTURES / "deck_fixture.ydke.txt"
FIXTURE_DECK_TEXT = FIXTURES / "deck_fixture.txt"


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
    import json

    from ygo_explorer.catalogue.normalize import normalize_dump
    from ygo_explorer.catalogue.views import attach_catalogue
    from ygo_explorer.collection.loader import open_collection

    cards = json.loads(fixture_dump.read_text(encoding="utf-8"))["data"]
    normalize_dump(
        cards,
        cards_path=tmp_path / "cards.parquet",
        card_sets_path=tmp_path / "card_sets.parquet",
        card_prices_path=tmp_path / "card_prices.parquet",
    )
    con = open_collection(fixture_csv)
    attach_catalogue(
        con,
        cards_path=tmp_path / "cards.parquet",
        card_sets_path=tmp_path / "card_sets.parquet",
        card_prices_path=tmp_path / "card_prices.parquet",
    )
    yield con
    con.close()


@pytest.fixture
def store(tmp_path: Path):
    from ygo_explorer.pricing.snapshots import SnapshotStore

    s = SnapshotStore(tmp_path / "snapshots.parquet")
    yield s
    s.close()
