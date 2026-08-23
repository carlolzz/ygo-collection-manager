/** Entering cards by hand: find the card, then describe each copy.
 *
 * The shape of this follows the scanner app's add flow — search, then printing,
 * then the details, with Near Mint / Unlimited / EN as the defaults — with one
 * difference that is the whole point of it. The scanner logs one copy at a time
 * from a camera, so a quantity there means "this many identical copies". Here
 * the copies stepper opens a *row per copy*, because the case that drives
 * someone to type instead of scan is a stack of the same card that is not the
 * same card at all: one German Common, one Italian Rare first edition, one
 * English Ultra Rare.
 *
 * Rows that do end up identical are folded back into one on the server, and the
 * footer says so before the save, so the stepper never has to be understood as
 * anything other than "how many copies am I adding".
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { getCataloguePrintings, searchCatalogue } from "../api";
import type { CatalogueCard, CataloguePrinting, NewEntry } from "../types";
import { ErrorNotice } from "./common";
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
  notes: string;
}

/** The card being added, whether the catalogue knows it or not. */
interface Chosen {
  passcode: string;
  name: string;
  /** Empty when the card was typed by hand — there is nothing to pick from. */
  printings: CataloguePrinting[];
  known: boolean;
}

/** A row before the folding decides how many copies it stands for. */
type Described = Omit<NewEntry, "quantity">;

/** Copies to rows: identical ones folded, quantities summed. What the server does. */
function toRows(chosen: Chosen, copies: Copy[], manual: ManualSet): NewEntry[] {
  const rows = new Map<string, NewEntry>();
  for (const copy of copies) {
    const printing = chosen.printings[copy.printing];
    const row: Described = {
      passcode: chosen.passcode,
      name: chosen.name,
      set_code: (printing ? printing.set_code : manual.set_code) || null,
      set_name: (printing ? printing.set_name : manual.set_name) || null,
      rarity: (printing ? printing.set_rarity : manual.rarity) || null,
      condition: copy.condition,
      edition: copy.edition,
      language: copy.language.trim().toUpperCase(),
      notes: copy.notes.trim() || null,
    };
    const key = entryKeyOf(row);
    const existing = rows.get(key);
    if (existing) existing.quantity += 1;
    else rows.set(key, { ...row, quantity: 1 });
  }
  return [...rows.values()];
}

interface ManualSet {
  set_code: string;
  set_name: string;
  rarity: string;
}

const NO_SET: ManualSet = { set_code: "", set_name: "", rarity: "" };

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
  const [manual, setManual] = useState<ManualSet>(NO_SET);
  const [byHand, setByHand] = useState(false);
  const [handPasscode, setHandPasscode] = useState("");
  const [handName, setHandName] = useState("");

  const defaults = useRef(loadDefaults());
  const [copies, setCopies] = useState<Copy[]>([]);
  const [showNotes, setShowNotes] = useState(false);

  // Debounced, but only to spare re-renders: the search is a local parquet scan,
  // not a request to YGOPRODeck, so there is no rate limit to respect here.
  useEffect(() => {
    const text = query.trim();
    if (!text) {
      setResults(null);
      setSearchError(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      setSearching(true);
      searchCatalogue(text)
        .then((found) => !cancelled && (setResults(found), setSearchError(null)))
        .catch((e: Error) => !cancelled && setSearchError(e.message))
        .finally(() => !cancelled && setSearching(false));
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  function firstCopy(printings: CataloguePrinting[]): Copy {
    return {
      // Auto-select when there is exactly one printing. Making someone tap a
      // one-option decision mostly gets them to skip it, and a copy logged with
      // no set is the answer that cannot be recovered later.
      printing: printings.length === 1 ? 0 : -1,
      ...defaults.current,
      notes: "",
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
    setManual(NO_SET);
    setChosen({ passcode: card.passcode, name: card.name, printings, known: true });
    setCopies([firstCopy(printings)]);
  }

  function chooseByHand() {
    const passcode = handPasscode.trim();
    const name = handName.trim();
    if (!/^[0-9]{1,8}$/.test(passcode) || !name) return;
    setManual(NO_SET);
    setChosen({ passcode, name, printings: [], known: false });
    setCopies([firstCopy([])]);
  }

  function back() {
    setChosen(null);
    setCopies([]);
    setManual(NO_SET);
  }

  function setCopyCount(next: number) {
    if (next < 1 || next > 99) return;
    setCopies((current) => {
      if (next <= current.length) return current.slice(0, next);
      // New rows clone the one above, so three identical copies are two clicks
      // and only the fields that differ have to be touched.
      const added = Array.from({ length: next - current.length }, () => ({
        ...current[current.length - 1],
        notes: "",
      }));
      return [...current, ...added];
    });
  }

  function editCopy(index: number, patch: Partial<Copy>) {
    setCopies((current) =>
      current.map((copy, i) => (i === index ? { ...copy, ...patch } : copy)),
    );
  }

  const rows = useMemo(
    () => (chosen ? toRows(chosen, copies, manual) : []),
    [chosen, copies, manual],
  );

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
            <p className="muted" style={{ fontSize: "0.76rem", margin: 0 }}>
              Searchable in English, German and Italian. Nothing here reaches the
              internet — it reads the card data already on disk.
            </p>

            {searchError && <ErrorNotice message={searchError} />}

            {results !== null && (
              <div className="picker-results">
                {results.length === 0 && !searching && (
                  <p className="muted" style={{ fontSize: "0.82rem" }}>
                    No card matches that.
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

            <div className="by-hand">
              {byHand ? (
                <>
                  <p className="muted" style={{ fontSize: "0.78rem", margin: 0 }}>
                    A card the cached data has never heard of. It is added exactly
                    as typed and shown with no card details until a refresh finds
                    it.
                  </p>
                  <div className="by-hand-fields">
                    <input
                      value={handPasscode}
                      inputMode="numeric"
                      placeholder="Passcode"
                      onChange={(e) => setHandPasscode(e.target.value)}
                    />
                    <input
                      value={handName}
                      placeholder="Card name"
                      onChange={(e) => setHandName(e.target.value)}
                    />
                    <button
                      className="subtle"
                      disabled={!/^[0-9]{1,8}$/.test(handPasscode.trim()) || !handName.trim()}
                      onClick={chooseByHand}
                    >
                      Use this
                    </button>
                  </div>
                </>
              ) : (
                <button className="subtle" onClick={() => setByHand(true)}>
                  Not listed? Add it by hand
                </button>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="between chosen-card">
              <span>
                <strong>{chosen.name}</strong>
                <span className="muted"> · {chosen.passcode}</span>
              </span>
              <button className="subtle" disabled={busy} onClick={back}>
                Change card
              </button>
            </div>

            {!chosen.known && (
              <div className="by-hand-fields">
                <input
                  value={manual.set_code}
                  placeholder="Set code"
                  onChange={(e) => setManual({ ...manual, set_code: e.target.value })}
                />
                <input
                  value={manual.set_name}
                  placeholder="Set name"
                  onChange={(e) => setManual({ ...manual, set_name: e.target.value })}
                />
                <input
                  value={manual.rarity}
                  placeholder="Rarity"
                  onChange={(e) => setManual({ ...manual, rarity: e.target.value })}
                />
              </div>
            )}

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
              <button className="subtle" onClick={() => setShowNotes((v) => !v)}>
                {showNotes ? "Hide notes" : "Add notes"}
              </button>
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
                    {showNotes && <th>Notes</th>}
                  </tr>
                </thead>
                <tbody>
                  {copies.map((copy, index) => (
                    <tr key={index}>
                      <td className="muted num">{index + 1}</td>
                      <td>
                        {chosen.known ? (
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
                        ) : (
                          <span className="muted">
                            {[manual.set_code, manual.rarity].filter(Boolean).join(" · ") ||
                              "No set recorded"}
                          </span>
                        )}
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
                      {showNotes && (
                        <td>
                          <input
                            value={copy.notes}
                            disabled={busy}
                            placeholder="Optional"
                            onChange={(e) => editCopy(index, { notes: e.target.value })}
                          />
                        </td>
                      )}
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
