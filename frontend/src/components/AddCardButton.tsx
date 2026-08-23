import { useState } from "react";
import { addEntries } from "../api";
import type { NewEntry } from "../types";
import AddCardDialog from "./AddCardDialog";

/** The one way to add a card by hand, used from the nav and from the empty state.
 *
 * Like the upload, the save writes a *new* timestamped export into the data
 * directory rather than editing one — so an add is undone by deleting the newest
 * file, and every export already there survives.
 */
export default function AddCardButton({
  onAdded,
  label,
  className,
}: {
  onAdded: () => void;
  label: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(rows: NewEntry[]) {
    setBusy(true);
    setError(null);
    try {
      await addEntries(rows);
      setOpen(false);
      onAdded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button className={className} onClick={() => (setError(null), setOpen(true))}>
        {label}
      </button>
      {open && (
        <AddCardDialog
          busy={busy}
          error={error}
          onSave={(rows) => void save(rows)}
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
