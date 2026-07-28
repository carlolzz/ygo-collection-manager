from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_CSV = FIXTURES / "collection_fixture.csv"
FIXTURE_DUMP = FIXTURES / "cardinfo_fixture.json"


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
