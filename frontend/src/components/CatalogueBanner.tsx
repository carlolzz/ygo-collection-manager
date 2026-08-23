import { useEffect, useRef, useState } from "react";
import { getCatalogueRefresh, startCatalogueRefresh } from "../api";
import { ErrorNotice, formatBytes, formatDays, formatEta } from "../components/common";
import { languageName } from "../components/LanguageFlag";
import type { CatalogueJob, CatalogueStatus } from "../types";

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
 *
 * Once started, the download reports itself: roughly forty megabytes over an
 * unknown line is long enough that a spinner alone reads as a hang. The server
 * measures the throughput and says how long the rest will take.
 */
export default function CatalogueBanner({
  status,
  onRefreshed,
}: {
  status: CatalogueStatus | null;
  onRefreshed: () => void;
}) {
  const [job, setJob] = useState<CatalogueJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Through a ref: the parent passes a fresh arrow every render, and putting
  // that in the effect below would restart the poll on each one.
  const refreshed = useRef(onRefreshed);
  refreshed.current = onRefreshed;

  const busy = job?.status === "pending" || job?.status === "running";

  useEffect(() => {
    if (!job || (job.status !== "pending" && job.status !== "running")) return;
    // Polls our own progress endpoint only — the download itself is one server
    // -side job, not a request per tick.
    const timer = window.setInterval(async () => {
      try {
        const next = await getCatalogueRefresh(job.id);
        setJob(next);
        if (next.status === "finished") refreshed.current();
      } catch (e) {
        setError((e as Error).message);
      }
    }, 700);
    return () => window.clearInterval(timer);
  }, [job]);

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
    setError(null);
    try {
      setJob(await startCatalogueRefresh(force));
    } catch (e) {
      setError((e as Error).message);
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

      {job && job.status !== "error" && <Progress job={job} />}

      {(error || job?.error) && (
        <div style={{ marginTop: "0.7rem" }}>
          <ErrorNotice message={error ?? job?.error ?? ""} />
        </div>
      )}
    </div>
  );
}

/** What has landed, and what that says about the time left.
 *
 * The bar stops at the server's download share rather than reaching 100% before
 * the work is over: deriving the catalogue reports no progress of its own, so
 * it gets a phase of its own and a fill that keeps moving instead of a
 * percentage nobody measured.
 */
function Progress({ job }: { job: CatalogueJob }) {
  const building = job.phase === "building";
  const eta = formatEta(job.eta_seconds);

  return (
    <div style={{ marginTop: "0.8rem" }}>
      <div className="between" style={{ fontSize: "0.82rem" }}>
        <span>
          {phaseLabel(job)}
          {!building && job.expected_bytes != null && (
            <span className="muted">
              {" "}
              · {formatBytes(job.downloaded_bytes)} of{" "}
              {formatBytes(job.expected_bytes)}
            </span>
          )}
        </span>
        <span className="muted">
          {job.status === "finished" ? "done" : (eta ?? "")}
        </span>
      </div>
      <div className="progress-track" style={{ marginTop: "0.4rem" }}>
        <div
          className={`progress-fill${building ? " working" : ""}`}
          style={{ width: `${job.status === "finished" ? 100 : job.percent}%` }}
        />
      </div>
    </div>
  );
}

function phaseLabel(job: CatalogueJob) {
  if (job.status === "finished") return "Card data updated";
  switch (job.phase) {
    case "cards":
      return "Downloading card data";
    case "names":
      return `Downloading ${languageName(job.language ?? "")} card names`;
    case "building":
      return "Building the catalogue…";
    default:
      return "Starting…";
  }
}
