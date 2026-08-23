/** Entering cards by hand: find the card, then describe each copy.
 *
 * The shape of this follows the scanner app's add flow — search, then printing,
 * then the details, with Near Mint / Unlimited as the defaults — with one
 * difference that is the whole point of it. The scanner logs one copy at a time
 * from a camera, so a quantity there means "this many identical copies". Here
 * the copies stepper opens a *row per copy*, because the case that drives
 * someone to type instead of scan is a stack of the same card that is not the
 * same card at all: one Italian Common, one Italian Rare first edition, one
 * English Ultra Rare.
 *
 * Rows that do end up identical are folded back into one on the server, and the
 * footer says so before the save, so the stepper never has to be understood as
 * anything other than "how many copies am I adding".
 *
 * Only cards the cached dump knows can be added. A passcode and a name typed
 * freehand were once accepted here, and what that mostly produced was a typo
 * living permanently in the ledger with no card data any refresh could ever
 * attach to it.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  getCatalogueStatus,
  getCataloguePrintings,
  imageUrl,
  searchCatalogue,
} from "../api";
import { useDeclinedLanguages } from "../declinedLanguages";
import { useAsync } from "../hooks";
import type { CatalogueCard, CataloguePrinting, NewEntry } from "../types";
import { ErrorNotice } from "./common";
import LanguageFlag, { languageName } from "./LanguageFlag";
import {
  CONDITIONS,
  ConditionSelect,
  EDITIONS,
  EditionSelect,
  LanguageSelect,
  entryKeyOf,
  printingLabel,
} from "./entryFields";

/** What a fresh row starts as, before the last-used values are read back. */
const FALLBACK = { condition: "NEAR_MINT", edition: "UNLIMITED", language: "EN" };

const DEFAULTS_KEY = "ygo.add_defaults";

/** The trio last saved, so the second card of a session is quicker than the first.
 *
 * A convenience only: nothing here is part of the collection, and a browser that
 * refuses storage simply gets the fallback every time.
 */
function loadDefaults(): typeof FALLBACK {
  try {
    const raw = localStorage.getItem(DEFAULTS_KEY);
    if (!raw) return FALLBACK;
    const saved = JSON.parse(raw) as Partial<typeof FALLBACK>;
    return {
      condition: CONDITIONS.includes(saved.condition as never)
        ? (saved.condition as string)
        : FALLBACK.condition,
      edition: EDITIONS.some((e) => e.value === saved.edition)
        ? (saved.edition as string)
        : FALLBACK.edition,
      language: saved.language?.trim() ? saved.language.toUpperCase() : FALLBACK.language,
    };
  } catch {
    return FALLBACK;
  }
}

function saveDefaults(values: typeof FALLBACK) {
  try {
    localStorage.setItem(DEFAULTS_KEY, JSON.stringify(values));
  } catch {
    /* a browser that refuses storage still gets a working dialog */
  }
}

/** One copy being described. `printing` indexes the card's printings, or -1. */
interface Copy {
  printing: number;
  condition: string;
  edition: string;
  language: string;
}

/** The card being added, as the catalogue has it. */
interface Chosen {
  passcode: string;
  name: string;
  printings: CataloguePrinting[];
}

/** A row before the folding decides how many copies it stands for. */
type Described = Omit<NewEntry, "quantity">;

/** Copies to rows: identical ones folded, quantities summed. What the server does. */
function toRows(chosen: Chosen, copies: Copy[]): NewEntry[] {
  const rows = new Map<string, NewEntry>();
  for (const copy of copies) {
    const printing = chosen.printings[copy.printing];
    const row: Described = {
      passcode: chosen.passcode,
      name: chosen.name,
      set_code: printing?.set_code || null,
      set_name: printing?.set_name || null,
      rarity: printing?.set_rarity || null,
      condition: copy.condition,
      edition: copy.edition,
      language: copy.language.trim().toUpperCase(),
      // The column still exists and rows loaded from an export still carry
      // theirs; a copy entered here simply never has one.
      notes: null,
    };
    const key = entryKeyOf(row);
    const existing = rows.get(key);
    if (existing) existing.quantity += 1;
    else rows.set(key, { ...row, quantity: 1 });
  }
  return [...rows.values()];
}

export default function AddCardDialog({
  busy,
  error,
  onSave,
  onCancel,
}: {
  busy: boolean;
  error: string | null;
  onSave: (rows: NewEntry[]) => void;
  onCancel: () => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CatalogueCard[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  const [chosen, setChosen] = useState<Chosen | null>(null);

  const defaults = useRef(loadDefaults());
  const [copies, setCopies] = useState<Copy[]>([]);

  // Which language's names to search, which is also the language the copies
  // start in — someone entering an Italian card is holding an Italian card.
  const [language, setLanguage] = useState(defaults.current.language);
  const catalogue = useAsync(getCatalogueStatus, []);
  const { declined, restore } = useDeclinedLanguages();
  // What the picker may offer, and which of those actually has names on disk.
  // A configured language whose index was never downloaded matches nothing at
  // all, so it is offered disabled rather than as a search that finds nothing.
  // A language turned down in the banner is dropped from the list entirely —
  // but only while its names are genuinely absent. Once they are on disk there
  // is nothing left to have declined, and hiding a search that would work would
  // be the preference outliving its reason.
  const cached = useMemo(
    () => new Set(["EN", ...(catalogue.data?.languages ?? [])]),
    [catalogue.data],
  );
  const offered = useMemo(
    () =>
      (catalogue.data?.search_languages ?? ["EN"]).filter(
        (code) => cached.has(code) || !declined.has(code),
      ),
    [catalogue.data, cached, declined],
  );
  const hidden = useMemo(
    () =>
      (catalogue.data?.search_languages ?? []).filter(
        (code) => !cached.has(code) && declined.has(code),
      ),
    [catalogue.data, cached, declined],
  );
  const known = catalogue.data !== null;
  const available = cached.has(language);

  // A stored default of, say, JP is a perfectly good language to *own* a card
  // in and no language to search in — and neither is one that is offered but
  // never downloaded. Either way, open on a search that works rather than on a
  // dead one the user has to notice and undo.
  useEffect(() => {
    if (known && !(offered.includes(language) && cached.has(language))) setLanguage("EN");
  }, [known, offered, cached, language]);

  // Debounced, but only to spare re-renders: the search is a local parquet scan,
  // not a request to YGOPRODeck, so there is no rate limit to respect here.
  useEffect(() => {
    const text = query.trim();
    if (!text || !available) {
      setResults(null);
      setSearchError(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      setSearching(true);
      searchCatalogue(text, language)
        .then((found) => !cancelled && (setResults(found), setSearchError(null)))
        .catch((e: Error) => !cancelled && setSearchError(e.message))
        .finally(() => !cancelled && setSearching(false));
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, language, available]);

  function firstCopy(printings: CataloguePrinting[]): Copy {
    return {
      // Auto-select when there is exactly one printing. Making someone tap a
      // one-option decision mostly gets them to skip it, and a copy logged with
      // no set is the answer that cannot be recovered later.
      printing: printings.length === 1 ? 0 : -1,
      condition: defaults.current.condition,
      edition: defaults.current.edition,
      language,
    };
  }

  async function choose(card: CatalogueCard) {
    setSearchError(null);
    let printings: CataloguePrinting[] = [];
    try {
      printings = await getCataloguePrintings(card.passcode);
    } catch (e) {
      setSearchError((e as Error).message);
      return;
    }
    setChosen({ passcode: card.passcode, name: card.name, printings });
    setCopies([firstCopy(printings)]);
  }

  function back() {
    setChosen(null);
    setCopies([]);
  }

  function setCopyCount(next: number) {
    if (next < 1 || next > 99) return;
    setCopies((current) => {
      if (next <= current.length) return current.slice(0, next);
      // New rows clone the one above, so three identical copies are two clicks
      // and only the fields that differ have to be touched.
      const added = Array.from({ length: next - current.length }, () => ({
        ...current[current.length - 1],
      }));
      return [...current, ...added];
    });
  }

  function editCopy(index: number, patch: Partial<Copy>) {
    setCopies((current) =>
      current.map((copy, i) => (i === index ? { ...copy, ...patch } : copy)),
    );
  }

  const rows = useMemo(() => (chosen ? toRows(chosen, copies) : []), [chosen, copies]);

  function save() {
    if (!chosen || rows.length === 0) return;
    const last = copies[copies.length - 1];
    saveDefaults({
      condition: last.condition,
      edition: last.edition,
      language: last.language.trim().toUpperCase() || FALLBACK.language,
    });
    onSave(rows);
  }

  return (
    <div className="modal-backdrop" onClick={busy ? undefined : onCancel}>
      <div
        className="modal modal-wide"
        role="dialog"
        aria-modal="true"
        aria-label="Add a card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="panel-title">Add a card</div>

        {chosen === null ? (
          <>
            <div className="search-bar">
              <div className="search-bar-query">
                <label className="sr-only" htmlFor="add-card-search">
                  Card name or passcode
                </label>
                <input
                  id="add-card-search"
                  autoFocus
                  value={query}
                  placeholder="Card name or 8-digit passcode"
                  onChange={(e) => setQuery(e.target.value)}
                />
              </div>
              <div className="search-bar-language lang-cell">
                <label className="sr-only" htmlFor="add-card-language">
                  Card language
                </label>
                <LanguageFlag code={language} />
                <select
                  id="add-card-language"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                >
                  {offered.map((code) => (
                    <option key={code} value={code} disabled={!cached.has(code)}>
                      {code} · {languageName(code)}
                      {cached.has(code) ? "" : " — not downloaded"}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <p className="muted" style={{ fontSize: "0.76rem", margin: 0 }}>
              Names are searched in {languageName(language)} only; a passcode works
              whatever the language. New copies start in this language. Nothing here
              reaches the internet — it reads the card data already on disk.
            </p>

            {/* The one place the decision is visible, so the one place to undo
                it: a language missing from the dropdown with no explanation is
                a preference that has become a mystery. */}
            {hidden.map((code) => (
              <p key={code} className="muted" style={{ fontSize: "0.76rem", margin: 0 }}>
                {languageName(code)} card names are turned off.{" "}
                <button className="link" onClick={() => restore(code)}>
                  Turn back on
                </button>
              </p>
            ))}

            {searchError && <ErrorNotice message={searchError} />}

            {known && !available && (
              <div className="notice">
                {languageName(language)} card names have not been downloaded yet.
                Update the card data to search in {languageName(language)}.
              </div>
            )}

            {available && results !== null && (
              <div className="picker-results">
                {results.length === 0 && !searching && (
                  <p className="muted picker-empty">
                    No card matches that in {languageName(language)}.
                  </p>
                )}
                {results.map((card) => (
                  <button
                    key={card.passcode}
                    className="picker-hit"
                    disabled={busy}
                    onClick={() => void choose(card)}
                  >
                    <span className="picker-hit-name">
                      {card.name}
                      {card.matched_name && (
                        <span className="muted">
                          {" "}
                          — {card.matched_name}
                          {card.matched_language && ` (${card.matched_language})`}
                        </span>
                      )}
                    </span>
                    <span className="muted picker-hit-meta">
                      {card.passcode}
                      {card.type && ` · ${card.type}`}
                      {card.owned_copies > 0 && ` · ${card.owned_copies} owned`}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            <div className="chosen-card-art">
              {/* The one confirmation that the right card was picked, which a
                  name alone cannot give when a card has alternate artworks and
                  three near-namesakes. The art comes from our own cache, which
                  fetches it upstream once if this card has never been viewed —
                  a card that is not owned yet usually has not been. Choosing a
                  card is a click, so that stays within what this app promises
                  about reaching YGOPRODeck, and the fetch happens only once. */}
              <img className="card-art" src={imageUrl(chosen.passcode)} alt={chosen.name} />
              <div className="between chosen-card">
                <span>
                  <strong>{chosen.name}</strong>
                  <span className="muted"> · {chosen.passcode}</span>
                </span>
                <button className="subtle" disabled={busy} onClick={back}>
                  Change card
                </button>
              </div>
            </div>

            <div className="between copies-bar">
              <span className="copies-stepper">
                <span className="muted">Copies</span>
                <button
                  className="subtle"
                  aria-label="One fewer copy"
                  disabled={busy || copies.length <= 1}
                  onClick={() => setCopyCount(copies.length - 1)}
                >
                  −
                </button>
                <strong className="num">{copies.length}</strong>
                <button
                  className="subtle"
                  aria-label="One more copy"
                  disabled={busy || copies.length >= 99}
                  onClick={() => setCopyCount(copies.length + 1)}
                >
                  +
                </button>
              </span>
            </div>

            <div className="table-wrap">
              <table className="copies-table">
                <thead>
                  <tr>
                    <th />
                    <th>Printing</th>
                    <th>Condition</th>
                    <th>Edition</th>
                    <th>Language</th>
                  </tr>
                </thead>
                <tbody>
                  {copies.map((copy, index) => (
                    <tr key={index}>
                      <td className="muted num">{index + 1}</td>
                      <td>
                        <select
                          value={copy.printing}
                          disabled={busy}
                          onChange={(e) =>
                            editCopy(index, { printing: Number(e.target.value) })
                          }
                        >
                          {/* An explicit answer, not a missing one: plenty of
                              cards are held loose with no set worth recording. */}
                          <option value={-1}>No set recorded</option>
                          {chosen.printings.map((p, i) => (
                            <option key={`${p.set_code}-${p.set_rarity}-${i}`} value={i}>
                              {printingLabel(p)}
                              {p.owned ? " ✓" : ""}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <ConditionSelect
                          value={copy.condition}
                          disabled={busy}
                          onChange={(condition) => editCopy(index, { condition })}
                        />
                      </td>
                      <td>
                        <EditionSelect
                          value={copy.edition}
                          disabled={busy}
                          onChange={(edition) => editCopy(index, { edition })}
                        />
                      </td>
                      <td>
                        <LanguageSelect
                          value={copy.language}
                          disabled={busy}
                          onChange={(language) => editCopy(index, { language })}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Said before the save, not after: the merge is the one thing about
                this dialog that could surprise someone. */}
            <p className="muted" style={{ fontSize: "0.76rem", margin: 0 }}>
              {copies.length} {copies.length === 1 ? "copy" : "copies"} →{" "}
              <strong>
                {rows.length} {rows.length === 1 ? "row" : "rows"}
              </strong>
              {rows.length < copies.length &&
                ". Copies matching in printing, condition, edition and language are" +
                  " one row. A row you already own is added to rather than repeated."}
            </p>
          </>
        )}

        {error && <div className="notice error">{error}</div>}

        <div className="modal-actions">
          <button className="subtle" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
          <button
            className="primary"
            disabled={busy || chosen === null || rows.length === 0}
            onClick={save}
          >
            {busy ? "Saving…" : "Add to collection"}
          </button>
        </div>
      </div>
    </div>
  );
}
