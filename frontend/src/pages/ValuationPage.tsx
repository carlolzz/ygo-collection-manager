import { useEffect, useRef, useState } from "react";
import {
  cancelRefinement,
  getCatalogueStatus,
  getRefinement,
  startRefinement,
  valueCollection,
} from "../api";
import {
  Amount,
  ErrorNotice,
  formatCondition,
  formatDays,
} from "../components/common";
import { useAction, useAsync } from "../hooks";
import { isRefinable, sourceFor, usePriceSource } from "../priceSource";
import type { RefineJob } from "../types";

export default function ValuationPage() {
  const { source } = usePriceSource();
  const catalogue = useAsync(getCatalogueStatus, []);
  const valuation = useAction(valueCollection);
  const perPrinting = isRefinable(source);

  // A total computed in one currency must not sit under a nav that now names
  // another. Changing the source discards the old answer rather than
  // relabelling it.
  const { setData } = valuation;
  useEffect(() => setData(null), [source, setData]);

  return (
    <div className="stack">
      <div className="panel">
        <div className="between">
          <div>
            <h1>Collection value</h1>
            <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
              Priced from {sourceFor(source).label} in{" "}
              {sourceFor(source).currency}, out of the cached card dump — so this
              costs no network requests at all and runs locally in a fraction of
              a second. Change the marketplace in the top bar.
            </p>
          </div>
          <div className="row">
            <button
              className="primary"
              onClick={() => valuation.trigger(source)}
              disabled={valuation.running}
            >
              {valuation.running ? "Calculating…" : "Calculate collection value"}
            </button>
          </div>
        </div>

        {valuation.error && (
          <div style={{ marginTop: "1rem" }}>
            <ErrorNotice message={valuation.error} />
          </div>
        )}

        {valuation.data && (
          <div style={{ marginTop: "1.2rem" }}>
            <div className="big-money">
              <Amount value={valuation.data.total} />
            </div>

            {/* The caveat sits next to the number, in plain words — not in a
                footnote, and never omitted. */}
            <div className="notice estimate" style={{ marginTop: "0.7rem" }}>
              <strong>This is an estimate.</strong> {valuation.data.caveat} Prices
              are from data fetched {formatDays(catalogue.data?.age_days)}.{" "}
              {perPrinting ? (
                <>
                  A card's rarity is only reflected where a printing-specific
                  price exists.
                </>
              ) : (
                <>
                  Printing-specific prices are quoted in USD only, so every row
                  here is priced per card and no rarity is reflected at all.
                </>
              )}
            </div>

            <div className="tiles" style={{ marginTop: "1rem" }}>
              <Tile
                value={valuation.data.per_printing_rows}
                label="Priced per printing"
                note={perPrinting ? "Rarity-specific" : "Unavailable in EUR"}
              />
              <Tile
                value={valuation.data.per_passcode_rows}
                label="Priced per card"
                note="Rarity not reflected"
              />
              <Tile
                value={valuation.data.unpriced_rows}
                label="Not priced at all"
                note={`${valuation.data.unpriced_copies} copies contribute nothing`}
              />
            </div>
          </div>
        )}
      </div>

      <RefinementPanel usable={perPrinting} />

      {valuation.data && valuation.data.rows.length > 0 && (
        <div className="panel">
          <div className="panel-title">Every row, and how it was priced</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Card</th>
                  <th>Printing</th>
                  <th>Condition</th>
                  <th>Edition</th>
                  <th className="num">Qty</th>
                  <th>Basis</th>
                  <th className="num">Unit</th>
                  <th className="num">×</th>
                  <th className="num">Subtotal</th>
                </tr>
              </thead>
              <tbody>
                {valuation.data.rows.map((row, i) => (
                  <tr key={i}>
                    <td>{row.name}</td>
                    <td className="muted">
                      {row.set_code ?? "no printing"}
                      {row.rarity ? ` · ${row.rarity}` : ""}
                    </td>
                    <td>{formatCondition(row.condition)}</td>
                    <td className="muted">{row.edition.toLowerCase()}</td>
                    <td className="num">{row.quantity}</td>
                    <td>
                      <span className={`pill${row.basis === "unpriced" ? " missing" : ""}`}>
                        {row.basis.replace("per_", "per ").replace("_", " ")}
                      </span>
                    </td>
                    <td className="num"><Amount value={row.unit_price} /></td>
                    <td className="num muted">{row.multiplier}</td>
                    <td className="num"><Amount value={row.subtotal} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: "0.78rem", marginBottom: 0 }}>
            The multiplier is a condition heuristic, not a market observation.
            Edition is shown but deliberately not priced — it moves value in
            reality by an amount that varies too much per card to guess.
          </p>
        </div>
      )}
    </div>
  );
}

function Tile({ value, label, note }: { value: number; label: string; note: string }) {
  return (
    <div className="tile">
      <div className="tile-value">{value.toLocaleString()}</div>
      <div className="tile-label">{label}</div>
      <div className="tile-note">{note}</div>
    </div>
  );
}

/** The one job that makes network requests, and only when started by hand.
 *
 * `usable` is false whenever the chosen source is not USD: the endpoint it
 * refines from quotes `set_price` in USD on every path, so there is nothing it
 * could add to a EUR total. Saying so beats a button that appears to work. */
function RefinementPanel({ usable }: { usable: boolean }) {
  const [job, setJob] = useState<RefineJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!job || job.status !== "running") {
      if (timer.current) window.clearInterval(timer.current);
      return;
    }
    // Polls our own progress endpoint only. No card data or price is fetched
    // by this loop; the worker queue on the server does the rate-limited work.
    timer.current = window.setInterval(async () => {
      try {
        setJob(await getRefinement(job.id));
      } catch (e) {
        setError((e as Error).message);
      }
    }, 700);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [job]);

  const running = job?.status === "running";
  const percent = job && job.total > 0 ? (job.done / job.total) * 100 : 0;

  return (
    <div className="panel">
      <div className="between">
        <div>
          <div className="panel-title" style={{ marginBottom: "0.2rem" }}>
            Refine printing prices
          </div>
          <p className="muted" style={{ margin: 0, fontSize: "0.85rem" }}>
            Looks up printing-specific prices the bulk dump is missing. This is
            the only part of the app that makes per-card requests — rate limited,
            resumable, and safe to cancel.
          </p>
        </div>
        <div className="row">
          {running ? (
            <button
              className="danger"
              onClick={async () => setJob(await cancelRefinement(job.id))}
            >
              Cancel
            </button>
          ) : (
            <button
              disabled={!usable}
              onClick={async () => {
                setError(null);
                try {
                  setJob(await startRefinement());
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Start refinement
            </button>
          )}
        </div>
      </div>

      {!usable && (
        <div className="notice" style={{ marginTop: "0.8rem" }}>
          Printing prices are quoted in USD on every path, so refining them adds
          nothing to a total priced in another currency. Switch the price source
          in the top bar to a USD marketplace to use this.
        </div>
      )}

      {error && <div style={{ marginTop: "0.8rem" }}><ErrorNotice message={error} /></div>}

      {job && (
        <div style={{ marginTop: "1rem" }}>
          <div className="between" style={{ fontSize: "0.85rem" }}>
            <span>
              {job.done} / {job.total}
              {job.current_set_code && (
                <span className="muted"> · {job.current_set_code}</span>
              )}
            </span>
            <span className="muted">{job.status}</span>
          </div>
          <div className="progress-track" style={{ marginTop: "0.4rem" }}>
            <div className="progress-fill" style={{ width: `${percent}%` }} />
          </div>
          <div className="muted" style={{ fontSize: "0.78rem", marginTop: "0.5rem" }}>
            {job.refined} refined · {job.unavailable} with no price · {job.failed} failed
            {job.skipped_fresh > 0 && ` · ${job.skipped_fresh} already fresh, skipped`}
          </div>
          {job.errors.length > 0 && (
            <details style={{ marginTop: "0.5rem", fontSize: "0.8rem" }}>
              <summary className="muted">{job.errors.length} failures</summary>
              <ul className="muted">
                {job.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
