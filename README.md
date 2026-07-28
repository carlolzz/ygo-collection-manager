# YGO Collection Explorer

A local, read-only web app for browsing, analysing and valuing a Yu-Gi-Oh card
collection. The collection itself is catalogued by a separate Flutter scanner
app, which is the single source of truth; this consumes its CSV export and never
writes back to it.

The full brief is in [initial_prompt.md](initial_prompt.md).

**Current state: build steps 1–3 (the backend).** No frontend, image cache or
valuation yet — see [Not built yet](#not-built-yet).

## Getting started

```bash
uv sync
uv run pytest                              # 98 tests, no network
uv run ygo-explorer refresh-dump           # one request; ~20 MB, ~14.5k cards
uv run ygo-explorer status
uv run uvicorn ygo_explorer.api.main:app --reload
```

Then open http://127.0.0.1:8000/docs.

The export is picked up from `data/ygo_collection_*.csv` (newest wins), or from
`YGO_COLLECTION_CSV` if set.

## How it fits together

Two sources, joined on the passcode:

- **The CSV is the ownership ledger** — what is owned, how many, in what
  condition, edition, language and printing. Read-only, validated on load.
- **YGOPRODeck's bulk `cardinfo.php` dump is the card catalogue** — type,
  attribute, race, atk/def/level, archetype, text, image URLs and prices. One
  request covers every card, cached on disk, refetched only when asked.

A row present in one and absent from the other is displayed, never dropped.

```
data/ygo_collection_*.csv ──> collection ──┐
                                            ├──> collection_enriched ──> /api/*
data/cache/cards.parquet  ──> cards     ────┘
```

### Things the data will do to you

Each of these is handled once, in one place, and pinned by a test:

| | |
|---|---|
| Passcodes carry leading zeros and vary in width (`00004041`, `8736823`) | Always strings. `passcode_key` ignores leading zeros **for joining only** |
| Alt-art passcodes are not top-level dump ids | The card index is built from the union of `id` and every `card_images[].id` |
| Missing values are `''`, never a NULL token | Normalized to NULL in the loading step, once |
| The exporter prefixes `=+-@` fields with `'` against formula injection | Exactly one leading apostrophe stripped from `name` and `notes` |
| A card occupies several rows | `SUM(quantity)` and `COUNT(DISTINCT passcode)` are never conflated, and no response field is called `count` |
| `set_code` is often empty | Per-printing logic degrades to per-passcode; those rows stay inside every total |
| YGOPRODeck mixes currencies in one response | Every price column names its currency (`cardmarket_price_eur`, `tcgplayer_price_usd`); amounts are `DECIMAL`, never float |

## Endpoints

| | |
|---|---|
| `GET /api/cards` | Filtered, sorted, paginated. One item per distinct card |
| `GET /api/cards/{passcode}` | Attributes, owned rows, and which printings are owned |
| `GET /api/stats` | Totals, distributions, acquisitions by month, the long tail |
| `GET /api/meta/filters` | Distinct values present, for building the filter bar |
| `GET /api/catalogue/status` | How old the card data is and how much it covers |
| `POST /api/catalogue/refresh` | Refetch the dump. The only network call |

Filters compose (AND across fields, OR within one) and read identically whether
they come from the CSV or the dump: `q`, `condition`, `edition`, `language`,
`set_code`, `set_name`, `rarity`, `type`, `frame_type`, `attribute`, `race`,
`archetype`, `level_min`, `level_max`, `has_printing`, `in_catalogue`.

`q` is folded with NFKD on both sides, so `Necrovalley` finds `Nécrovalley`.

Counts reflect the active filters: `?condition=POOR` reports the copies in POOR,
not the whole stack.

## Rules the code holds itself to

- The CSV is read-only input. Nothing writes to it.
- Nothing touches the network except `POST /api/catalogue/refresh` and
  `ygo-explorer refresh-dump`. Not on page load, scroll, filter change or timer.
- One token bucket at 8 req/s, shared. YGOPRODeck blocks an IP for an hour above
  20 req/s.
- Card art is downloaded, never hotlinked — their guide requires it. `/api/cards`
  returns the upstream URL as `source_image_url`, for the image cache to fetch
  once; it is not for the browser to load.
- Money is `DECIMAL` with an explicit currency. Never summed across currencies.

## Not built yet

Steps 4–8 of the brief: the React frontend (Recharts, URL-driven filter state),
the local image cache, statistics charts, and valuation — the `PriceProvider`
protocol, the snapshot store, condition multipliers and the two "Calculate
value" actions. The catalogue already caches everything valuation needs.

Two notes for whoever builds valuation:

1. **Per-printing pricing is nearly free.** `card_sets[].set_price` is already in
   the cached dump, so refining a rarity-specific price is a local join.
   `cardsetsinfo.php` is only needed for set codes the dump omits.
2. **`set_price` is USD-only**, on both paths. A EUR (`cardmarket_price`) run
   therefore cannot be refined per printing — which is why `tcgplayer_price`
   (USD) is the configured default in `config.py`. Present per-currency totals
   side by side, or convert through an explicit dated FX rate. Never implicitly.
