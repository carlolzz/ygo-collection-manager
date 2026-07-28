import { useRef, useState } from "react";
import { uploadCollection } from "../api";

/** Shown when no export is loaded — the container's first run.
 *
 * The app deliberately starts rather than refusing to boot, so this page is
 * what a friend sees on `docker run` before they have added anything.
 */
export default function EmptyState({ onLoaded }: { onLoaded: () => void }) {
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
    <div className="empty">
      <h2>No collection loaded yet</h2>
      <p>
        This app reads a CSV exported by the scanner app. It never writes to it —
        the scanner stays the single source of truth for what you own.
      </p>

      <p style={{ marginTop: "1.5rem" }}>
        <button
          className="primary"
          disabled={busy}
          onClick={() => input.current?.click()}
        >
          {busy ? "Loading…" : "Choose a CSV export"}
        </button>
      </p>
      <input
        ref={input}
        type="file"
        accept=".csv,text/csv"
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void upload(file);
        }}
      />

      {error && (
        <p style={{ maxWidth: 620, margin: "1rem auto" }}>
          <span className="notice error">{error}</span>
        </p>
      )}

      <p className="muted" style={{ marginTop: "2rem" }}>
        Or drop the file into the mounted <code>data/</code> directory and restart:
      </p>
      <pre>docker run -p 8000:8000 -v "$PWD/data:/data" charliegordonmouse/ygo-explorer</pre>
    </div>
  );
}
