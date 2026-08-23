"""Paths and tunable constants, resolved once."""

from __future__ import annotations

import os
from pathlib import Path

# src/ygo_explorer/config.py -> src/ygo_explorer -> src -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("YGO_DATA_DIR", PROJECT_ROOT / "data"))
CACHE_DIR = Path(os.environ.get("YGO_CACHE_DIR", DATA_DIR / "cache"))

DUMP_PATH = CACHE_DIR / "cardinfo.json"
DUMP_META_PATH = CACHE_DIR / "cardinfo.meta.json"
CARDS_PARQUET = CACHE_DIR / "cards.parquet"
CARD_SETS_PARQUET = CACHE_DIR / "card_sets.parquet"
CARD_PRICES_PARQUET = CACHE_DIR / "card_prices.parquet"
CARD_NAMES_PARQUET = CACHE_DIR / "card_names.parquet"

IMAGE_CACHE_DIR = CACHE_DIR / "images"

# The built SPA. Absent in development (Vite serves it); present in the image.
FRONTEND_DIST = Path(
    os.environ.get("YGO_FRONTEND_DIST", PROJECT_ROOT / "frontend" / "dist")
)

# Fetch art for owned cards at startup. Off in tests, so a suite never reaches
# the network; on in the app, where it is a few seconds for a few hundred cards.
WARM_IMAGES_ON_STARTUP = os.environ.get("YGO_WARM_IMAGES", "1") != "0"

CARDINFO_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
CARDSETSINFO_URL = "https://db.ygoprodeck.com/api/v7/cardsetsinfo.php"

# Extra dumps fetched so the card picker can be searched in the languages a
# European collection is actually printed in. The base dump is English; each of
# these is one more request of ~19 MB and covers TCG cards only, so a card with
# no localized name simply stays findable by its English one.
#
# YGOPRODeck localizes into fr, de, it and pt. Only the ones asked for are
# fetched — every added language is another 19 MB in the mount and another
# request on every refresh.
CATALOGUE_LANGUAGES: tuple[str, ...] = ("de", "it")

#: The language the base dump is in, and the language a card's stored name is
#: always written in. A localized name is for *finding* a card, never for
#: recording one: the collection's `name` column has to agree with the scanner's.
BASE_LANGUAGE = "EN"

# YGOPRODeck blocks an IP for an hour above 20 req/s. Stay well under it; every
# provider and every job shares this one budget.
REQUESTS_PER_SECOND = 8.0

# Snapshots older than this are refetched only when the user asks. Named here so
# the UI and the valuation job cannot disagree about what "fresh" means.
PRICE_STALENESS_DAYS = 14

# The valuation source field, and therefore the currency of every total. Never
# sum across fields.
#
# Cardmarket, because that is where a European collection is actually bought and
# sold. The cost is real and is stated in the UI rather than hidden: per-printing
# refinement (card_sets[].set_price, cardsetsinfo.php) is USD-only, so a EUR run
# prices every row per passcode and can never reflect rarity. Pick a USD field to
# get that back — there is no conversion between the two.
DEFAULT_PRICE_FIELD = "cardmarket_price"
DEFAULT_PRICE_CURRENCY = "EUR"


def collection_csv_path() -> Path:
    """Locate the collection export.

    ``YGO_COLLECTION_CSV`` wins if set; otherwise the newest
    ``ygo_collection_*.csv`` in the data directory.
    """
    override = os.environ.get("YGO_COLLECTION_CSV")
    if override:
        return Path(override)
    exports = sorted(DATA_DIR.glob("ygo_collection_*.csv"))
    if not exports:
        raise FileNotFoundError(
            f"No collection export found in {DATA_DIR}. Export one from the scanner "
            "app, or set YGO_COLLECTION_CSV to its path."
        )
    return exports[-1]
