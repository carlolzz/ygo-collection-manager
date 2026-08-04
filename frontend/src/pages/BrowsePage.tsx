import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getFilterOptions, imageUrl, listCards } from "../api";
import { ErrorNotice, Loading } from "../components/common";
import { LanguageFlags, languageName } from "../components/LanguageFlag";
import { useAsync } from "../hooks";
import type { CardSummary, FilterOptions } from "../types";

const PAGE_SIZE = 60;

/** Every filter lives in the URL, so a view is shareable and bookmarkable. */
const FILTER_KEYS = [
  "q", "condition", "edition", "language", "rarity", "set_name",
  "type", "frame_type", "attribute",
  "monster_type", "spell_type", "trap_type", "archetype",
] as const;

type FilterKey = (typeof FILTER_KEYS)[number];

const LABELS: Record<FilterKey, string> = {
  q: "Name",
  condition: "Condition",
  edition: "Edition",
  language: "Language",
  rarity: "Rarity",
  set_name: "Set",
  type: "Type",
  frame_type: "Frame",
  attribute: "Attribute",
  monster_type: "Monster type",
  spell_type: "Spell type",
  trap_type: "Trap type",
  archetype: "Archetype",
};

const SORTS: [string, string][] = [
  ["name", "Name (A–Z)"],
  ["card_type", "Card type (monsters first)"],
  ["copies", "Most copies"],
  ["newest", "Recently added"],
  ["oldest", "Oldest first"],
  ["level", "Level"],
  ["atk", "ATK"],
];

/** How dense the grid is. Not a filter — it never counts toward "Clear". */
const VIEWS: [string, string][] = [
  ["", "Comfortable"],
  ["compact", "Compact"],
];

export default function BrowsePage() {
  const [params, setParams] = useSearchParams();
  // `view` is a display choice, not a query — dropping it here keeps toggling
  // density from re-fetching the same page of cards.
  const query = useMemo(() => {
    const q = new URLSearchParams(params);
    q.delete("view");
    return q.toString();
  }, [params]);

  const options = useAsync(getFilterOptions, []);
  const page = useAsync(() => listCards(query), [query]);

  const offset = Number(params.get("offset") ?? 0);
  const compact = params.get("view") === "compact";

  function update(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    // Any filter change returns to the first page; staying on page 4 of a
    // narrower result is never what was meant.
    if (key !== "offset") next.delete("offset");
    setParams(next);
  }

  /** Clearing drops the filters, not how you chose to look at the results. */
  function clearFilters() {
    setParams(compact ? new URLSearchParams({ view: "compact" }) : new URLSearchParams());
  }

  const activeCount = useMemo(
    () => FILTER_KEYS.filter((k) => params.get(k)).length,
    [params],
  );

  return (
    <div className="stack">
      <FilterBar
        params={params}
        options={options.data}
        onChange={update}
        onClear={clearFilters}
        activeCount={activeCount}
      />

      {page.error && <ErrorNotice message={page.error} />}
      {page.loading && !page.data && <Loading what="cards" />}

      {page.data && (
        <>
          <div className="between">
            <div className="muted">
              <strong>{page.data.total_cards.toLocaleString()}</strong> distinct
              cards · <strong>{page.data.total_copies.toLocaleString()}</strong>{" "}
              copies
              {activeCount > 0 && " matching these filters"}
            </div>
            <div className="row">
              <span className="muted" style={{ fontSize: "0.8rem" }}>Sort</span>
              <select
                value={params.get("sort") ?? "name"}
                onChange={(e) => update("sort", e.target.value)}
                style={{ width: "auto" }}
              >
                {SORTS.map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
              <div className="segmented">
                {VIEWS.map(([value, label]) => (
                  <button
                    key={label}
                    className={value === (params.get("view") ?? "") ? "active" : ""}
                    onClick={() => update("view", value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {page.data.items.length === 0 ? (
            <div className="empty">
              <h2>Nothing matches</h2>
              <p>No cards in the collection satisfy every active filter.</p>
            </div>
          ) : (
            <div className={compact ? "card-grid compact" : "card-grid"}>
              {page.data.items.map((card) => (
                <CardTile key={card.passcode} card={card} compact={compact} />
              ))}
            </div>
          )}

          <Pager
            offset={offset}
            total={page.data.total_cards}
            onGo={(next) => update("offset", next ? String(next) : "")}
          />
        </>
      )}
    </div>
  );
}

/** Compact drops the type line and moves the copy count onto the art, so the tile
 *  is art plus one line of name — the count is the one thing too useful to lose.
 *  The flags follow it onto the art, on the opposite corner. */
function CardTile({ card, compact }: { card: CardSummary; compact: boolean }) {
  const copies = `${card.total_copies} ${card.total_copies === 1 ? "copy" : "copies"}`;
  const langs = card.languages.map(languageName).join(", ");
  return (
    <Link
      to={`/card/${card.passcode}`}
      className="card"
      title={compact ? `${card.name} · ${copies}${langs && ` · ${langs}`}` : langs || undefined}
    >
      <div className="card-art-wrap">
        <img
          className="card-art"
          src={imageUrl(card.passcode)}
          alt={card.name}
          loading="lazy"
        />
        {compact && (
          <>
            <LanguageFlags codes={card.languages} max={2} className="overlay" />
            <span className="copies-badge overlay">×{card.total_copies}</span>
          </>
        )}
      </div>
      <div className="card-body">
        <div className="card-name">{card.name}</div>
        {!compact && (
          <div className="card-meta">
            <LanguageFlags codes={card.languages} />{" "}
            <span className="copies-badge">{copies}</span>{" "}
            {card.in_catalogue ? (card.type ?? "") : "card details unknown"}
          </div>
        )}
      </div>
    </Link>
  );
}

function FilterBar({
  params,
  options,
  onChange,
  onClear,
  activeCount,
}: {
  params: URLSearchParams;
  options: FilterOptions | null;
  onChange: (key: string, value: string) => void;
  onClear: () => void;
  activeCount: number;
}) {
  // Ownership filters come from the CSV and card-attribute filters from the
  // catalogue, but they are presented identically on purpose.
  const selects: [FilterKey, string[]][] = options
    ? [
        ["condition", options.condition],
        ["edition", options.edition],
        ["language", options.language],
        ["rarity", options.rarity],
        ["set_name", options.set_name],
        ["type", options.type],
        ["attribute", options.attribute],
        // Upstream calls all three "race" in one column; they are unrelated
        // taxonomies, so they get one dropdown each.
        ["monster_type", options.monster_type],
        ["spell_type", options.spell_type],
        ["trap_type", options.trap_type],
        ["archetype", options.archetype],
        ["frame_type", options.frame_type],
      ]
    : [];

  return (
    <div className="panel">
      <div className="filters">
        <div>
          <label htmlFor="q">{LABELS.q}</label>
          <input
            id="q"
            value={params.get("q") ?? ""}
            onChange={(e) => onChange("q", e.target.value)}
          />
        </div>
        {selects.map(([key, values]) => (
          <div key={key}>
            <label htmlFor={key}>{LABELS[key]}</label>
            <select
              id={key}
              value={params.get(key) ?? ""}
              onChange={(e) => onChange(key, e.target.value)}
            >
              <option value="">Any</option>
              {values.map((v) => (
                <option key={v} value={v}>
                  {key === "condition"
                    ? v.replace(/_/g, " ").toLowerCase()
                    : key === "language"
                      ? `${v} — ${languageName(v)}`
                      : v}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
      <div className="filter-actions">
        <button className="subtle" onClick={onClear} disabled={activeCount === 0}>
          Clear {activeCount > 0 && `(${activeCount})`}
        </button>
        <span className="muted" style={{ fontSize: "0.78rem" }}>
          Filters compose, and the URL holds them: copy it to share this view.
        </span>
      </div>
    </div>
  );
}

function Pager({
  offset,
  total,
  onGo,
}: {
  offset: number;
  total: number;
  onGo: (offset: number) => void;
}) {
  if (total <= PAGE_SIZE) return null;
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pages = Math.ceil(total / PAGE_SIZE);
  return (
    <div className="row" style={{ justifyContent: "center" }}>
      <button disabled={offset <= 0} onClick={() => onGo(Math.max(0, offset - PAGE_SIZE))}>
        Previous
      </button>
      <span className="muted">
        Page {page} of {pages}
      </span>
      <button
        disabled={offset + PAGE_SIZE >= total}
        onClick={() => onGo(offset + PAGE_SIZE)}
      >
        Next
      </button>
    </div>
  );
}
