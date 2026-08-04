import { useRef, useState } from "react";
import { previewCollection, uploadCollection, type UploadMode } from "../api";
import type { UploadPreview } from "../types";
import UploadDialog from "./UploadDialog";

/** The one way to load a CSV, used both on first run and from the nav afterwards.
 *
 * The upload writes a *new* timestamped export into the data directory rather
 * than overwriting anything — the newest one is what the app then reads, and the
 * previous file is still there.
 *
 * With a collection already loaded there is a real decision to make about the
 * rows both files hold, so the file is previewed first and the dialog asks.
 * With nothing loaded there is nothing to decide, and asking would be noise.
 */
export default function UploadButton({
  onLoaded,
  label,
  className,
  hasCollection = false,
}: {
  onLoaded: () => void;
  label: string;
  className?: string;
  hasCollection?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{ file: File; preview: UploadPreview } | null>(null);

  async function run<T>(work: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError(null);
    try {
      return await work();
    } catch (e) {
      setError((e as Error).message);
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function choose(file: File) {
    if (!hasCollection) {
      await run(async () => {
        await uploadCollection(file, "replace");
        onLoaded();
      });
      return;
    }
    const preview = await run(() => previewCollection(file));
    if (preview) setPending({ file, preview });
  }

  async function confirm(mode: UploadMode) {
    if (!pending) return;
    const done = await run(async () => {
      await uploadCollection(pending.file, mode);
      return true;
    });
    if (done) {
      setPending(null);
      onLoaded();
    }
  }

  function cancel() {
    setPending(null);
    setError(null);
  }

  return (
    <>
      <button className={className} disabled={busy} onClick={() => input.current?.click()}>
        {busy && !pending ? "Loading…" : label}
      </button>
      <input
        ref={input}
        type="file"
        accept=".csv,text/csv"
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          // Cleared so picking the same file twice still fires a change event.
          e.target.value = "";
          if (file) void choose(file);
        }}
      />
      {error && !pending && <span className="notice error upload-error">{error}</span>}
      {pending && (
        <UploadDialog
          fileName={pending.file.name}
          preview={pending.preview}
          busy={busy}
          error={error}
          onConfirm={(mode) => void confirm(mode)}
          onCancel={cancel}
        />
      )}
    </>
  );
}
