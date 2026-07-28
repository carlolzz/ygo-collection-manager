# YGO Collection Explorer

A local, read-only web app for browsing, analysing and valuing a Yu-Gi-Oh card
collection, and for checking a deck list against what you actually own.

The collection is catalogued by a separate Flutter scanner app, which is the
single source of truth; this consumes its CSV export and never writes back to it.

The full brief is in [initial_prompt.md](initial_prompt.md).

---

## Running it with Docker

The published image ships **empty** — no collection data, no card art. You supply
a CSV export, and the card catalogue downloads itself on first use into the
mounted directory.

```bash
mkdir -p data                  # drop your ygo_collection_*.csv in here
docker compose up
```

Then open <http://localhost:8000>. Without a compose file:

```bash
docker run -p 8000:8000 -v "$PWD/data:/data" carlolzz/ygo-explorer
```

If you have no CSV to hand, start it anyway — the app comes up with an empty
collection and offers an upload button.

> **Git Bash on Windows**: it rewrites `-v /c/…:/data` into nonsense and Docker
> silently falls back to an anonymous volume, so your data vanishes on the next
> `docker run`. Use PowerShell, prefix the command with `MSYS_NO_PATHCONV=1`, or
> just use `docker compose`, which is unaffected.

### What lives in the mount

| | |
|---|---|
| `data/ygo_collection_*.csv` | your export — read, never written |
| `data/cache/cardinfo.json` | the YGOPRODeck bulk dump, ~21 MB, fetched on request |
| `data/cache/*.parquet` | derived card, printing and price tables |
| `data/cache/images/` | card art, downloaded once per card |
| `data/cache/price_snapshots.parquet` | every price ever fetched, append-only |

Deleting `data/cache/` costs nothing but a re-download.

## Running it from source

```bash
uv sync
uv run pytest                              # 197 tests, none touch the network
uv run ygo-explorer refresh-dump           # one request; ~21 MB, ~14.5k cards
uv run ygo-explorer status
uv run uvicorn ygo_explorer.api.main:app --reload
cd frontend && npm install && npm run dev  # Vite on :5173, proxying /api
```

API docs at <http://127.0.0.1:8000/docs>. The export is picked up from
`data/ygo_collection_*.csv` (newest wins), or `YGO_COLLECTION_CSV` if set.

---

## How it fits together

Two sources, joined on the passcode:

- **The CSV is the ownership ledger** — what is owned, how many, in what
  condition, edition, language and printing.
- **YGOPRODeck's bulk `cardinfo.php` dump is the card catalogue** — type,
  attribute, race, atk/def/level, archetype, text, image URLs *and prices*. One
  request covers every card, cached on disk, refetched only when asked.

A row present in one and absent from the other is displayed, never dropped.

### Things the data will do to you

Each is handled once, in one place, and pinned by a test:

| | |
|---|---|
| Passcodes carry leading zeros and vary in width (`00004041`, `8736823`) | Always strings. `passcode_key` ignores leading zeros **for joining only** |
| Alt-art passcodes are not top-level dump ids | The card index unions `id` with every `card_images[].id` — 14,641 passcodes across 14,476 cards |
| Missing values are `''`, never a NULL token | Normalized to NULL once, on load |
| The exporter prefixes `=+-@` fields with `'` against formula injection | Exactly one leading apostrophe stripped from `name` and `notes` |
| A card occupies several rows | `SUM(quantity)` and `COUNT(DISTINCT passcode)` are never conflated, and no response field is called `count` |
| `set_code` is often empty | Per-printing logic degrades to per-passcode; those rows stay inside every total |
| YGOPRODeck mixes currencies in one response | `Money` carries its currency and refuses to add two; amounts are `Decimal`, and serialize as strings so no JSON float rounds a price |

---

## Features

**Browse.** Card grid with real artwork, filter bar, and a detail view showing
stats, card text, the printings you own and the condition/edition/language
breakdown. Filters compose and live in the URL, so a view is shareable. Name
search folds NFKD on both sides — `Necrovalley` finds `Nécrovalley`.

**Statistics.** Totals, distributions by condition/type/attribute/archetype/set,
acquisitions over time, and the long tail. Every chart says *which* count it is
showing.

**Valuation**, on an explicit click and never otherwise. Because prices ride
along in the cached dump, valuing the whole collection is a local join costing
zero network requests. Next to the total, in plain words: that it is an estimate,
how many rows were priced per-printing versus per-passcode, how many could not be
priced, the currency, and how old the data is.

**Deck check.** Paste a `ydke://` code, a `.ydk` file or a plain typed list; get
what you are missing and roughly what it would cost.

### How the deck check counts

- **Format is detected, not declared.** A ydke code is `ydke://<b64>!<b64>!<b64>!`
  where each section is base64 of a little-endian `uint32` array — packed binary,
  not text — and a repeated passcode means multiple copies.
- **Demand is aggregated across main, extra and side**, because you need those
  copies at the same time. A list running 2 Mystical Space Typhoon main and 1
  side needs three cards.
- **Ownership matches on the card, not the passcode.** An alternate artwork is
  still the card, and the catalogue already maps alt-art ids back.
- **Spare copies are not progress.** Owning six of a card a deck runs three of
  contributes three.
- **A line matching no card is reported, never silently dropped.**

---

## Two notes on pricing

**Per-printing prices are for valuing, not for shopping.** Only 12,363 of 44,138
printing rows carry a `set_price`, and that sparse subset is unrepresentative in
both directions — Maxx "C" has 1 of 10 printings priced and reads $27.00 against
a $3.49 per-passcode figure, while Thunder King Rai-Oh reads $4.57 against
$10.94. So valuation uses the printing price where the printing is known (it is
the more specific fact about a card you hold), and the deck check uses the
per-passcode market low, which has 96.5% coverage and is what a playable copy
actually costs.

**`set_price` is USD on every path**, both in the dump and from
`cardsetsinfo.php`. A EUR (`cardmarket_price`) run therefore cannot be refined
per printing at all — which is why `tcgplayer_price` is the default in
`config.py`. Present per-currency totals side by side, or convert through an
explicit dated FX rate. Never implicitly.

---

## Rules the code holds itself to

- The CSV is read-only input. The upload endpoint writes a *new* timestamped
  file and never modifies an existing one.
- Nothing touches the network except an explicit click: the catalogue refresh,
  the printing-price refinement job, and a lazy image fetch on first view. Not on
  page load, scroll, filter change or timer — and a test asserts it.
- One token bucket at 8 req/s, shared by everything. YGOPRODeck blocks an IP for
  an hour above 20 req/s.
- Card art is downloaded, never hotlinked — their guide requires it.
- Every price read goes through the append-only snapshot store. No provider is
  called from a request handler.
- Money is `Decimal` with an explicit currency, never summed across currencies.

## Not built

Cardmarket and TCGplayer are credential-gated stubs that raise a clear
`CredentialsRequired`, per the brief. Deck building, `.ydk` export, editing the
collection and card scanning are all explicit non-goals.
