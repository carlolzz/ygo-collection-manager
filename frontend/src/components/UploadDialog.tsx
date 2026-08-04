import { useState } from "react";
import type { UploadMode } from "../api";
import type { UploadPreview } from "../types";

/** The three things that can sensibly happen to rows both files describe.
 *
 * Worded for someone who has never heard of a merge: the question is about
 * cards, not about rows, and every option says what it is *for* rather than
 * what it does to the database.
 */
const CHOICES: { mode: UploadMode; title: string; detail: string }[] = [
  {
    mode: "merge_sum",
    title: "Add the quantities together",
    detail:
      "Two copies plus two copies becomes four. Use this when the file only " +
      "holds cards you have scanned since last time.",
  },
  {
    mode: "merge_keep",
    title: "Keep one of each duplicate",
    detail:
      "Cards in both stay at the new file's quantity, and anything new is " +
      "added. Use this when the file is a fresh export of everything you own.",
  },
  {
    mode: "replace",
    title: "Replace my collection",
    detail: "Forget what is loaded now and use only this file.",
  },
];

export default function UploadDialog({
  fileName,
  preview,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  fileName: string;
  preview: UploadPreview;
  busy: boolean;
  error: string | null;
  onConfirm: (mode: UploadMode) => void;
  onCancel: () => void;
}) {
  // Keeping duplicates is the safe default: it is the only choice that cannot
  // silently double a collection when the same export is uploaded twice.
  const [mode, setMode] = useState<UploadMode>("merge_keep");

  return (
    <div className="modal-backdrop" onClick={busy ? undefined : onCancel}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Load a CSV"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="panel-title">Load a CSV</div>

        <p className="muted" style={{ fontSize: "0.82rem" }}>
          {/* Not in the title: .panel-title uppercases, and a file name is the
              user's, not ours to shout. */}
          <strong className="filename">{fileName}</strong>
          <br />
          You already have{" "}
          <strong>{preview.current_rows.toLocaleString()}</strong> rows loaded.
          Of the <strong>{preview.incoming_rows.toLocaleString()}</strong> in
          this file, <strong>{preview.overlapping_rows.toLocaleString()}</strong>{" "}
          {preview.overlapping_rows === 1 ? "is" : "are"} already in your
          collection and <strong>{preview.new_rows.toLocaleString()}</strong>{" "}
          {preview.new_rows === 1 ? "is" : "are"} new.
        </p>

        <div className="choices">
          {CHOICES.map((choice) => (
            <label
              key={choice.mode}
              className={choice.mode === mode ? "choice selected" : "choice"}
            >
              <input
                type="radio"
                name="upload-mode"
                value={choice.mode}
                checked={choice.mode === mode}
                disabled={busy}
                onChange={() => setMode(choice.mode)}
              />
              <span>
                <strong>{choice.title}</strong>
                <span className="muted">{choice.detail}</span>
              </span>
            </label>
          ))}
        </div>

        <p className="muted" style={{ fontSize: "0.75rem" }}>
          Whichever you pick, the CSV files already in the data folder are left
          exactly as they are — the result is written as a new one.
        </p>

        {error && <div className="notice error">{error}</div>}

        <div className="modal-actions">
          <button className="subtle" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
          <button className="primary" disabled={busy} onClick={() => onConfirm(mode)}>
            {busy ? "Loading…" : "Load CSV"}
          </button>
        </div>
      </div>
    </div>
  );
}
