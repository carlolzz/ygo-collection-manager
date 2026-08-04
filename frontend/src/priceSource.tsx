/** The one price source the whole app values in.
 *
 * The server has no FX rate and will never invent one, so the currency of a
 * total is a consequence of which dump field a run reads — not a display
 * setting. That is why this holds a source field rather than a currency: the
 * user picks a marketplace, and the currency follows from it.
 */

import { createContext, useContext, useEffect, useState } from "react";

export interface PriceSource {
  /** The dump field, sent to the API verbatim. */
  field: string;
  label: string;
  currency: string;
}

/** Cardmarket first: it is the default, and it is what a European collection
 *  is actually bought and sold in. */
export const SOURCES: PriceSource[] = [
  { field: "cardmarket_price", label: "Cardmarket", currency: "EUR" },
  { field: "tcgplayer_price", label: "TCGplayer", currency: "USD" },
  { field: "ebay_price", label: "eBay", currency: "USD" },
  { field: "amazon_price", label: "Amazon", currency: "USD" },
  { field: "coolstuffinc_price", label: "CoolStuffInc", currency: "USD" },
];

/** Must match config.DEFAULT_PRICE_FIELD on the server. */
export const DEFAULT_SOURCE = "cardmarket_price";

const STORAGE_KEY = "ygo.price_source";

export const sourceFor = (field: string): PriceSource =>
  SOURCES.find((s) => s.field === field) ?? SOURCES[0];

/** Per-printing prices exist in USD only, so a EUR run can never be
 *  rarity-accurate and the refinement job cannot help it. */
export const isRefinable = (field: string) => sourceFor(field).currency === "USD";

function read(): string {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    // A hand-edited or stale key must not reach the API and earn a 422.
    if (stored && SOURCES.some((s) => s.field === stored)) return stored;
  } catch {
    /* localStorage throws outright in some privacy modes */
  }
  return DEFAULT_SOURCE;
}

interface Store {
  source: string;
  setSource: (field: string) => void;
}

const Context = createContext<Store>({ source: DEFAULT_SOURCE, setSource: () => {} });

export function PriceSourceProvider({ children }: { children: React.ReactNode }) {
  const [source, setSource] = useState(read);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, source);
    } catch {
      /* the choice still holds for this session */
    }
  }, [source]);

  return <Context.Provider value={{ source, setSource }}>{children}</Context.Provider>;
}

export const usePriceSource = () => useContext(Context);

/** One control, rendered wherever the source is offered. */
export function PriceSourceSelect() {
  const { source, setSource } = usePriceSource();
  return (
    <select
      value={source}
      onChange={(e) => setSource(e.target.value)}
      aria-label="Price source"
      title="Prices, and the currency of every total, come from this marketplace"
    >
      {SOURCES.map((s) => (
        <option key={s.field} value={s.field}>
          {s.label} ({s.currency})
        </option>
      ))}
    </select>
  );
}
