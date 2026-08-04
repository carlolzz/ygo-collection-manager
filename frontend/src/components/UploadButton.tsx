import { useRef, useState } from "react";
import { uploadCollection } from "../api";

/** The one way to load a CSV, used both on first run and from the nav afterwards.
 *
 * The upload writes a *new* timestamped export into the data directory rather
 * than overwriting anything — the newest one is what the app then reads, and the
 * previous file is still there.
 */
export default function UploadButton({
  onLoaded,
  label,
  className,
}: {
  onLoaded: () => void;
  label: string;
  className?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      await uploadCollection(file);
      onLoaded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button className={className} disabled={busy} onClick={() => input.current?.click()}>
        {busy ? "Loading…" : label}
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
          if (file) void upload(file);
        }}
      />
      {error && <span className="notice error upload-error">{error}</span>}
    </>
  );
}
