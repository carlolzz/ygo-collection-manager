import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { deleteEntry, editEntry } from "../api";
import { useCollectionReload } from "../collectionReload";
import type { CataloguePrinting, NewEntry, OwnedRow } from "../types";
import EditEntryDialog from "./EditEntryDialog";
import { keyFor } from "./entryFields";

/** Editing or removing one owned row, from the card page.
 *
 * Like every other write in this app, both land on a *new* timestamped export
 * and leave the current one on disk — so either is undone by deleting the
 * newest file, and nothing is ever actually destroyed.
 */
export default function EditEntryButton({
  passcode,
  name,
  row,
  siblings,
  printings,
}: {
  passcode: string;
  name: string;
  row: OwnedRow;
  siblings: OwnedRow[];
  printings: CataloguePrinting[];
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reloadCollection = useCollectionReload();
  const navigate = useNavigate();

  /** Run a write, then get off this page before the reload remounts it.
   *
   * `leaves` is true when the card will have no rows left afterwards: the
   * remounted page would refetch, 404, and show an error about a card the user
   * has just finished emptying.
   */
  async function run(write: () => Promise<unknown>, leaves: boolean) {
    setBusy(true);
    setError(null);
    try {
      await write();
      setOpen(false);
      if (leaves) navigate("/");
      reloadCollection();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // An edit never leaves the card — the dialog offers no way to change which
  // card a row belongs to, only how the copies are described.
  const save = (replacement: NewEntry) =>
    void run(() => editEntry(keyFor(passcode, row), replacement), false);

  return (
    <>
      <button className="subtle" onClick={() => (setError(null), setOpen(true))}>
        Edit
      </button>
      {open && (
        <EditEntryDialog
          passcode={passcode}
          name={name}
          row={row}
          siblings={siblings}
          printings={printings}
          busy={busy}
          error={error}
          onSave={save}
          onDelete={() =>
            void run(() => deleteEntry(keyFor(passcode, row)), siblings.length === 1)
          }
          onCancel={() => {
            if (busy) return;
            setOpen(false);
            setError(null);
          }}
        />
      )}
    </>
  );
}
