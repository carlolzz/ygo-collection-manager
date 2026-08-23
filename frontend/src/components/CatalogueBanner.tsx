import { useState } from "react";
import { refreshCatalogue } from "../api";
import { ErrorNotice, formatDays } from "../components/common";
import { languageName } from "../components/LanguageFlag";
import type { CatalogueStatus } from "../types";

/** Prompts for the one download the app cannot work without.
 *
 * A fresh install has no card catalogue, so no card attributes, no artwork and
 * no prices — and nothing else in the UI would explain why. The download is
 * still a click, never automatic.
 *
 * It also prompts for a cache that predates a configured language index. That
 * cache is otherwise perfectly healthy and recent enough that nothing else here
 * would mention it, while the card picker's language dropdown has an option
 * that cannot be selected — this is the only route to the forced refresh that
 * fixes it.
 */
export default function CatalogueBanner({
  status,
  onRefreshed,
}: {
  status: CatalogueStatus | null;
  onRefreshed: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!status) return null;

  const missing = status.catalogue_cards === 0;
  const stale = !missing && (status.age_days ?? 0) > 30;
  // Configured to be searchable, but with no names on disk to search.
  const missingNames = missing
    ? []
    : status.search_languages.filter(
        (code) => code !== "EN" && !status.languages.includes(code),
      );
  if (!missing && !stale && missingNames.length === 0) return null;

  async function download(force: boolean) {
    setBusy(true);
    setError(null);
    try {
      await refreshCatalogue(force);
      onRefreshed();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="notice estimate" style={{ marginBottom: "1.25rem" }}>
      <div className="between">
        <div>
          {missing ? (
            <>
              <strong>Card data not downloaded yet.</strong> Until it is, cards
              show without artwork, stats or prices. It's a single ~21 MB
              download from YGOPRODeck, and it only happens when you ask.
            </>
          ) : stale ? (
            <>
              <strong>Card data is {formatDays(status.age_days)}.</strong> Prices
              and new cards may be out of date.
            </>
          ) : (
            <>
              <strong>
                {missingNames.map(languageName).join(" and ")} card names are not
                downloaded.
              </strong>{" "}
              Cards can only be searched in English until they are. Updating
              refetches the card data along with them.
            </>
          )}
        </div>
        <button
          className="primary"
          // Forced whenever there is an existing cache to replace: without it
          // the refresh sees a cached dump and returns having done nothing.
          onClick={() => download(stale || missingNames.length > 0)}
          disabled={busy}
          style={{ whiteSpace: "nowrap" }}
        >
          {busy ? "Downloading…" : missing ? "Download card data" : "Update now"}
        </button>
      </div>
      {error && (
        <div style={{ marginTop: "0.7rem" }}>
          <ErrorNotice message={error} />
        </div>
      )}
    </div>
  );
}
