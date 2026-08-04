import UploadButton from "./UploadButton";

/** Shown when no export is loaded — the container's first run.
 *
 * The app deliberately starts rather than refusing to boot, so this page is
 * what a friend sees on `docker run` before they have added anything.
 */
export default function EmptyState({ onLoaded }: { onLoaded: () => void }) {
  return (
    <div className="empty">
      <h2>No collection loaded yet</h2>
      <p>
        This app reads a CSV exported by the scanner app. It never writes to it —
        the scanner stays the single source of truth for what you own.
      </p>

      <p style={{ marginTop: "1.5rem" }}>
        <UploadButton onLoaded={onLoaded} label="Choose a CSV export" className="primary" />
      </p>

      <p className="muted" style={{ marginTop: "2rem" }}>
        Or drop the file into the mounted <code>data/</code> directory and restart:
      </p>
      <pre>docker run -p 8000:8000 -v "$PWD/data:/data" charliegordonmouse/ygo-explorer</pre>
    </div>
  );
}
