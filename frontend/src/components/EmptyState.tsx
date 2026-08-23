import AddCardButton from "./AddCardButton";
import UploadButton from "./UploadButton";

/** Shown when no export is loaded — the container's first run.
 *
 * The app deliberately starts rather than refusing to boot, so this page is
 * what a friend sees on `docker run` before they have added anything. Both ways
 * in are offered here: a CSV from the scanner, or the first card typed straight
 * in, which is what someone with no scanner app at all needs.
 */
export default function EmptyState({ onLoaded }: { onLoaded: () => void }) {
  return (
    <div className="empty">
      <h2>No collection loaded yet</h2>
      <p>
        Load a CSV exported by the scanner app, or start from nothing and add
        cards by hand. Either way, nothing already in the data folder is ever
        modified — every change is written as a new file.
      </p>

      <p style={{ marginTop: "1.5rem", display: "flex", gap: "0.5rem", justifyContent: "center" }}>
        <UploadButton onLoaded={onLoaded} label="Choose a CSV export" className="primary" />
        <AddCardButton onAdded={onLoaded} label="Add a card by hand" className="subtle" />
      </p>

      <p className="muted" style={{ marginTop: "2rem" }}>
        Or drop the file into the mounted <code>data/</code> directory and restart:
      </p>
      <pre>docker run -p 8000:8000 -v "$PWD/data:/data" charliegordonmouse/ygo-explorer</pre>
    </div>
  );
}
