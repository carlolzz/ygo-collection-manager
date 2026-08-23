# YGO Collection Manager

A local web app for browsing, analysing and valuing a Yu-Gi-Oh card collection,
for adding cards to it by hand, and for checking a deck list against what you
actually own.

Cards are catalogued either by the separate [Flutter scanner app](https://github.com/carlolzz/ygo-card-scanner) — point a
phone camera at a card — or typed straight in here, by name or by the 8-digit
passcode. The CSV is the interchange format between the two, and it travels in
both directions: an export from the scanner loads here, and what is added here
imports back.

> **Naming.** The distribution and this repository are `ygo-collection-manager`.
> The Python import package is still `ygo_explorer`, the CLI is still
> `ygo-explorer`, and the published image is still
> `charliegordonmouse/ygo-explorer` — renaming those would break every existing
> install for no benefit.

---

> **Not a developer?** [**GETTING-STARTED.md**](GETTING-STARTED.md) walks through
> installing Docker and running this, step by step, with no assumed knowledge.

## Running it with Docker

The published image ships **empty**, no collection data, no card art. You supply
a CSV export, and the card catalogue downloads itself on first use into the
mounted directory.

```bash
mkdir -p data                  # drop your ygo_collection_*.csv in here
docker compose up
```

Then open <http://localhost:8000>. Without a compose file:

```bash
docker run -p 8000:8000 -v "$PWD/data:/data" charliegordonmouse/ygo-explorer
```

If you have no CSV to hand, start it anyway; the app comes up with an empty
collection and offers an upload button.

> **Git Bash on Windows**: it rewrites `-v /c/…:/data` into nonsense and Docker
> silently falls back to an anonymous volume, so your data vanishes on the next
> `docker run`. Use PowerShell, prefix the command with `MSYS_NO_PATHCONV=1`, or
> just use `docker compose`, which is unaffected.

### What lives in the mount

| | |
|---|---|
| `data/ygo_collection_*.csv` | your collection; the newest one is loaded, older ones are kept |
| `data/cache/cardinfo.json` | the YGOPRODeck bulk dump, ~21 MB, fetched on request |
| `data/cache/cardinfo.{de,it}.json` | the German and Italian name indexes, ~19 MB each |
| `data/cache/*.parquet` | derived card, printing, name and price tables |
| `data/cache/images/` | card art, downloaded once per card |
| `data/cache/price_snapshots.parquet` | every price ever fetched, append-only |

Deleting `data/cache/` costs nothing but a re-download.

## Running it from source

```bash
uv sync
uv run pytest                              # 304 tests, none touch the network
uv run ygo-explorer refresh-dump           # 3 requests; ~59 MB, ~14.5k cards
uv run ygo-explorer status
uv run uvicorn ygo_explorer.api.main:app --reload
cd frontend && npm install && npm run dev  # Vite on :5173, proxying /api
```

API docs at <http://127.0.0.1:8000/docs>. The export is picked up from
`data/ygo_collection_*.csv` (newest wins), or `YGO_COLLECTION_CSV` if set.

---

## How it fits together

Two sources, joined on the passcode:

- **The CSV is the ownership ledger**: what is owned, how many, in what
  condition, edition, language and printing. It is written only by appending a
  *new* timestamped file; no file already in the directory is ever modified.
- **YGOPRODeck's bulk `cardinfo.php` dump is the card catalogue**: type,
  attribute, race, atk/def/level, archetype, text, image URLs *and prices*. One
  request covers every card, cached on disk, refetched only when asked. Two more
  requests fetch the German and Italian name indexes, which exist purely so the
  card picker can be searched in them.

A row present in one and absent from the other is displayed, never dropped.

### Things the data will do to you

Each is handled once, in one place, and pinned by a test:

| | |
|---|---|
| Passcodes carry leading zeros and vary in width (`00004041`, `8736823`) | Always strings. `passcode_key` ignores leading zeros **for joining only** |
| Alt-art passcodes are not top-level dump ids | The card index unions `id` with every `card_images[].id` 14,641 passcodes across 14,476 cards |
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
search folds NFKD on both sides: `Necrovalley` finds `Nécrovalley`. Each tile
carries the flags of the languages it is held in, drawn as inline SVG rather
than emoji because Windows ships no flag glyphs.

**Add a card by hand.** Search by name or by the 8-digit passcode against the
card data already on disk — no network request, and searchable in **English,
German and Italian**, so a card held as *Kartenkavallerist* is found by that
name and stored under its English one. Then say how many copies, and get **one
row per copy**: each with its own printing, condition, edition and language. The
case this exists for is a stack that is not really a stack — one German Common
Unlimited, one Italian Rare 1st Edition, one English Ultra Rare, entered in a
single dialog. Rows that do agree on all four are folded into one with the
quantities summed, the dialog says so before you save, and a row you already own
is added to rather than repeated. Rarity is not its own field: you pick a
printing and the rarity comes with it, because YGOPRODeck's ~90 free-form rarity
strings do not make a usable list. A card the cached data has never heard of can
still be added, by typing the passcode and name, and it displays like any other
row with its card details simply unknown.

**Edit or remove a row.** Every row on a card's page has an *Edit* button, which
opens the same four fields the add dialog uses — printing, condition, edition,
language — plus the number of copies and a note. Editing a row into a
combination you already own **merges** into it rather than making a second row
of the same thing, and the dialog says which row it is about to merge with and
what the total will be. Setting the quantity *sets* it, so recording that you
sold two of five is one number. Delete lives in the same dialog behind a
confirm, and neither an edit nor a delete destroys anything: both write a new
export and leave the previous one on disk.

**Download the collection.** *Download CSV* in the nav hands back the loaded
export as it stands on disk, in the same twelve-column format the scanner
writes — so it opens in a spreadsheet, and it loads straight back in through the
button next to it. Mostly there for the container, where the data directory is a
volume that is otherwise awkward to reach.

**Loading an export**, either by dropping it in the mount or through the button.
Onto an existing collection the two are merged rather than one silently winning:
the app counts the overlap by the natural key first, then asks whether to sum the
quantities, keep one of each duplicate (the uploaded file's quantity wins), or
replace outright. The merged result is written as a *new* timestamped CSV, so
every export already in the directory survives untouched.

**Statistics.** Totals, distributions by condition/type/attribute/archetype/set,
acquisitions over time, and the long tail. Every chart says *which* count it is
showing.

**Valuation**, on an explicit click and never otherwise. Because prices ride
along in the cached dump, valuing the whole collection is a local join costing
zero network requests. Next to the total, in plain words: that it is an estimate,
how many rows were priced per-printing versus per-passcode, how many could not be
priced, the currency, and how old the data is.

**Deck check.** Paste a `ydke://` code, a `.ydk` file or a plain typed list; get
what you are missing and roughly what it would cost, plus the shortfall written
back out as a copyable `ydke://` code and a copyable text list.

**One price source, chosen in the top bar** and remembered between visits. It
governs the valuation, the deck check and the per-card figure alike, so two
numbers in the app are never quoted in different currencies. It names a
marketplace rather than a currency — Cardmarket (EUR) by default, TCGplayer,
eBay, Amazon or CoolStuffInc in USD — because the currency is a consequence of
which marketplace a run reads, not a display setting. Nothing is converted; see
the pricing notes below.

### How the deck check counts

- **Format is detected, not declared.** A ydke code is `ydke://<b64>!<b64>!<b64>!`
  where each section is base64 of a little-endian `uint32` array (packed binary,
  not text) and a repeated passcode means multiple copies.
- **Demand is aggregated across main, extra and side**, because you need those
  copies at the same time. A list running 2 Mystical Space Typhoon main and 1
  side needs three cards.
- **Ownership matches on the card, not the passcode.** An alternate artwork is
  still the card, and the catalogue already maps alt-art ids back.
- **Spare copies are not progress.** Owning six of a card a deck runs three of
  contributes three.
- **A line matching no card is reported, never silently dropped.**
- **The shortfall comes back out in both formats.** Owned copies are spent main
  first, then extra, then side, so the export says which zone each missing copy
  belongs to. Both forms parse back in, so pasting either one returns the same
  shortfall.

---

## Two notes on pricing

**Per-printing prices are for valuing, not for shopping.** Only 12,363 of 44,138
printing rows carry a `set_price`, and that sparse subset is unrepresentative in
both directions: Maxx "C" has 1 of 10 printings priced and reads $27.00 against
a $3.49 per-passcode figure, while Thunder King Rai-Oh reads $4.57 against
$10.94. So valuation uses the printing price where the printing is known (it is
the more specific fact about a card you hold), and the deck check uses the
per-passcode market low, which has 96.5% coverage and is what a playable copy
actually costs.

**`set_price` is USD on every path**, both in the dump and from
`cardsetsinfo.php`. A EUR (`cardmarket_price`) run therefore cannot be refined
per printing at all: every row is priced per passcode and no rarity is
reflected. That trade is made deliberately — `cardmarket_price` is the default
in `config.py`, because Cardmarket is where a European collection is actually
bought and sold, and the cost is stated in the UI rather than shown as a silent
zero. Pick a USD source in the top bar to get per-printing pricing and the
refinement job back. Present per-currency totals side by side, or convert
through an explicit dated FX rate. Never implicitly.

---

## Rules the code holds itself to

- No existing export is ever modified. Every write path — the upload,
  hand-entered rows, an edit, a delete — writes a *new* timestamped file, so any
  save is undone by deleting the newest one and every earlier file survives byte
  for byte. It is also why the download can simply hand over a file: whatever is
  loaded is already a valid export.
- Adding a card is a *merge*, not a second code path. The rows are staged as an
  export and folded in with the same natural-key grouping the upload uses, so
  there is exactly one implementation of what it means to combine two rows.
- Editing a row is that same merge with the old row taken out first, which is
  what makes setting a quantity set it rather than add to it — and what makes an
  edit onto a row already owned merge into it for free, with no case handling
  anywhere. Deleting is the same operation with nothing folded back in.
- A row is identified by the seven-column natural key, matched NULL-safely,
  because the export contract has no row id and inventing one would mean this
  app's CSVs were no longer the scanner's CSVs.
- Nothing touches the network except an explicit click: the catalogue refresh,
  the printing-price refinement job, and a lazy image fetch on first view. Not on
  page load, scroll, filter change or timer and a test asserts it. The card
  picker searches the cached dump, so typing in it costs nothing.
- One token bucket at 8 req/s, shared by everything. YGOPRODeck blocks an IP for
  an hour above 20 req/s.
- Card art is downloaded, never hotlinked, since their guide requires it.
- Every price read goes through the append-only snapshot store. No provider is
  called from a request handler.
- Money is `Decimal` with an explicit currency, never summed across currencies.

## Not built

Card scanning stays in the scanner app, which is what a camera is for. Deck
building and `.ydk` export are explicit non-goals. There is no undo button
either — the undo is deleting the newest CSV, which works for every kind of
save and needs no code.

Cardmarket and TCGplayer are credential-gated stubs that raise a clear
`CredentialsRequired`, per the brief.

Localized names cover German and Italian, set in `CATALOGUE_LANGUAGES` in
`config.py`. YGOPRODeck also publishes French and Portuguese; each one added is
another ~19 MB in the mount and another request on every refresh. They are an
index for *finding* a card and never a name a card is stored under — the ledger's
`name` column has to keep agreeing with the scanner's.
