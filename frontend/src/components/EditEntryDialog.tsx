/** Correcting a row that is already owned, or removing it.
 *
 * Deliberately much smaller than the add dialog. There is no card to find and no
 * copies stepper: the row already *is* a stack of identical copies, so the
 * quantity is a number to set rather than a count of rows to open.
 *
 * The one thing worth explaining to whoever is using it is what happens when an
 * edit lands on a combination they already own. The server merges the two — the
 * scanner app's rule — so the footer says so before the save rather than leaving
 * a row to apparently vanish.
 */

import { useState } from "react";
import type { CataloguePrinting, NewEntry, OwnedRow } from "../types";
import {
  ConditionSelect,
  EditionSelect,
  LanguageSelect,
  entryKeyOf,
  keyFor,
  printingLabel,
} from "./entryFields";

/** What the form holds. The set fields travel together, as one printing. */
interface Draft {
  set_code: string | null;
  set_name: string | null;
  rarity: string | null;
  condition: string;
  edition: string;
  language: string;
  quantity: number;
  /** Carried, never edited. The form offers no control for it, but a saved row
   *  replaces the old one and the incoming side wins the merge — so dropping it
   *  here would erase whatever note the row arrived with. */
  notes: string;
}

const draftOf = (row: OwnedRow): Draft => ({
  set_code: row.set_code,
  set_name: row.set_name,
  rarity: row.rarity,
  condition: row.condition,
  edition: row.edition,
  language: row.language,
  quantity: row.quantity,
  notes: row.notes ?? "",
});

const asPrinting = (d: Pick<Draft, "set_code" | "set_name" | "rarity">): CataloguePrinting => ({
  set_code: d.set_code,
  set_name: d.set_name,
  set_rarity: d.rarity,
  set_price_usd: null,
  owned: true,
});

/** The printings to offer: everything the catalogue lists, plus — if the row is
 *  on a printing the catalogue has never heard of — the one it is actually on.
 *
 *  Without that second half, editing a hand-typed set code would silently
 *  rewrite it to whichever printing happened to be first in the list. */
function options(row: OwnedRow, catalogue: CataloguePrinting[]): CataloguePrinting[] {
  if (row.set_code === null) return catalogue;
  const known = catalogue.some(
    (p) => p.set_code === row.set_code && p.set_rarity === row.rarity,
  );
  return known ? catalogue : [asPrinting(row), ...catalogue];
}

export default function EditEntryDialog({
  passcode,
  name,
  row,
  siblings,
  printings,
  busy,
  error,
  onSave,
  onDelete,
  onCancel,
}: {
  passcode: string;
  name: string;
  row: OwnedRow;
  /** Every row of this card, so a merge can be predicted before the save. */
  siblings: OwnedRow[];
  printings: CataloguePrinting[];
  busy: boolean;
  error: string | null;
  onSave: (replacement: NewEntry) => void;
  onDelete: () => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftOf(row));
  const [confirming, setConfirming] = useState(false);

  const choices = options(row, printings);
  // The index of the chosen printing, or -1 for "no set recorded" — the same
  // convention the add dialog uses.
  const chosen = choices.findIndex(
    (p) => p.set_code === draft.set_code && p.set_rarity === draft.rarity,
  );

  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  function choosePrinting(index: number) {
    const printing = choices[index];
    set(
      printing
        ? {
            set_code: printing.set_code,
            set_name: printing.set_name,
            rarity: printing.set_rarity,
          }
        : { set_code: null, set_name: null, rarity: null },
    );
  }

  const replacement: NewEntry = {
    passcode,
    name,
    set_code: draft.set_code,
    set_name: draft.set_name,
    rarity: draft.rarity,
    condition: draft.condition,
    edition: draft.edition,
    language: draft.language.trim().toUpperCase(),
    quantity: draft.quantity,
    notes: draft.notes.trim() || null,
  };

  const changed =
    entryKeyOf(replacement) !== entryKeyOf(keyFor(passcode, row)) ||
    draft.quantity !== row.quantity;

  // Best effort, and it does not have to be exhaustive: it cannot see a row
  // under another passcode, and the server does the right thing either way.
  const collides = siblings.find(
    (other) =>
      other !== row && entryKeyOf(keyFor(passcode, other)) === entryKeyOf(replacement),
  );

  return (
    <div className="modal-backdrop" onClick={busy ? undefined : onCancel}>
      <div
        className="modal modal-wide"
        role="dialog"
        aria-modal="true"
        aria-label="Edit this entry"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="panel-title">Edit this entry</div>

        <div className="between chosen-card">
          <span>
            <strong>{name}</strong>
            <span className="muted"> · {passcode}</span>
          </span>
        </div>

        <div className="table-wrap">
          <table className="copies-table">
            <thead>
              <tr>
                <th>Printing</th>
                <th>Condition</th>
                <th>Edition</th>
                <th>Language</th>
                <th className="num">Copies</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <select
                    value={chosen}
                    disabled={busy}
                    onChange={(e) => choosePrinting(Number(e.target.value))}
                    aria-label="Printing"
                  >
                    <option value={-1}>No set recorded</option>
                    {choices.map((p, i) => (
                      <option key={`${p.set_code}-${p.set_rarity}-${i}`} value={i}>
                        {printingLabel(p)}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <ConditionSelect
                    value={draft.condition}
                    disabled={busy}
                    onChange={(condition) => set({ condition })}
                  />
                </td>
                <td>
                  <EditionSelect
                    value={draft.edition}
                    disabled={busy}
                    onChange={(edition) => set({ edition })}
                  />
                </td>
                <td>
                  <LanguageSelect
                    value={draft.language}
                    disabled={busy}
                    onChange={(language) => set({ language })}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    min={1}
                    max={9999}
                    value={draft.quantity}
                    disabled={busy}
                    aria-label="Copies"
                    onChange={(e) => set({ quantity: Math.max(1, Number(e.target.value) || 1) })}
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {collides && (
          <p className="muted" style={{ fontSize: "0.76rem", margin: 0 }}>
            You already own {collides.quantity}{" "}
            {collides.quantity === 1 ? "copy" : "copies"} described exactly this way, so
            the two become{" "}
            <strong>one row of {collides.quantity + draft.quantity}</strong>.
          </p>
        )}

        <p className="muted" style={{ fontSize: "0.76rem", margin: 0 }}>
          Saving writes a new export and leaves the current one on disk, so this is
          undone by deleting the newest CSV.
        </p>

        {error && <div className="notice error">{error}</div>}

        <div className="modal-actions split">
          {confirming ? (
            <button className="danger" disabled={busy} onClick={onDelete}>
              {busy
                ? "Deleting…"
                : `Really remove ${row.quantity} ${row.quantity === 1 ? "copy" : "copies"}?`}
            </button>
          ) : (
            <button className="danger subtle" disabled={busy} onClick={() => setConfirming(true)}>
              Delete
            </button>
          )}
          <span className="row">
            <button className="subtle" disabled={busy} onClick={onCancel}>
              Cancel
            </button>
            <button
              className="primary"
              disabled={busy || !changed}
              onClick={() => onSave(replacement)}
            >
              {busy ? "Saving…" : "Save changes"}
            </button>
          </span>
        </div>
      </div>
    </div>
  );
}
