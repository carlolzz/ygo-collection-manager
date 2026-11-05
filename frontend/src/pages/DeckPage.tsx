import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  analyzeDeck,
  deleteDeckCheck,
  getDeckCheck,
  listDeckChecks,
  updateDeckCheck,
} from "../api";
import { Amount, CopyButton, ErrorNotice, Loading } from "../components/common";
import { useAsync } from "../hooks";
import { sourceFor, usePriceSource } from "../priceSource";
import type { DeckAnalysis, DeckCheck } from "../types";

const PLACEHOLDER = `Paste a ydke:// code, a .ydk file, or a plain list:

Main Deck:
3 Sabersaurus
2 Rescue Rabbit
1 Heavy Storm

Side Deck:
2 Maxx "C"`;

const copies = (n: number) => `${n.toLocaleString()} ${n === 1 ? "copy" : "copies"}`;

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export default function DeckPage() {
  const { checkId } = useParams();
  const navigate = useNavigate();
  const { source } = usePriceSource();

  const [text, setText] = useState("");
  const [result, setResult] = useState<DeckAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const checks = useAsync(listDeckChecks, []);
  const { reload: reloadChecks } = checks;

  // What is on screen, as "id|source". A check just run is already showing,
  // so the address changing to its id must not fetch it a second time.
  const shown = useRef<string | null>(null);

  // Opening a check by its address, and re-pricing it when the source changes:
  // costs are in the source's currency, so a change invalidates the answer.
  useEffect(() => {
    if (!checkId) {
      shown.current = null;
      setResult(null);
      return;
    }
    const key = `${checkId}|${source}`;
    if (shown.current === key) return;
    shown.current = key;
    let cancelled = false;
    setRunning(true);
    setError(null);
    getDeckCheck(checkId, source)
      .then((value) => {
        if (cancelled) return;
        setResult(value);
        setText(value.text);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setResult(null);
        setError(e.message);
      })
      .finally(() => !cancelled && setRunning(false));
    return () => {
      cancelled = true;
      // An unfinished load must be retried, not mistaken for one that landed.
      if (shown.current === key) shown.current = null;
    };
  }, [checkId, source]);

  async function runCheck() {
    setRunning(true);
    setError(null);
    try {
      const value = await analyzeDeck(text, source);
      setResult(value);
      reloadChecks();
      if (value.check) {
        shown.current = `${value.check.id}|${source}`;
        if (value.check.id !== checkId) navigate(`/deck/${value.check.id}`);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  /** After a flag, rename or delete: holds move between decks, so both the
   *  list and the check on screen may have changed. */
  const refresh = useCallback(async () => {
    reloadChecks();
    if (!checkId) return;
    try {
      setResult(await getDeckCheck(checkId, source));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [checkId, source, reloadChecks]);

  async function change(id: string, patch: { name?: string; owned?: boolean }) {
    await updateDeckCheck(id, patch);
    await refresh();
  }

  async function remove(id: string) {
    await deleteDeckCheck(id);
    if (id === checkId) {
      // Gone, so there is nothing to re-fetch — only the list to update.
      setText("");
      setResult(null);
      navigate("/deck");
      reloadChecks();
      return;
    }
    await refresh();
  }

  const check = result?.check ?? null;

  return (
    <div className="stack">
      <div className="panel">
        <h1>Deck check</h1>
        <p className="muted" style={{ marginTop: 0, fontSize: "0.85rem" }}>
          Paste a deck list and see which cards you are missing and roughly what
          the missing ones would cost. The format is detected automatically:
          EDOPro's ydke code, its .ydk export, or a plain typed list all work.
          Costs are quoted from {sourceFor(source).label} in{" "}
          {sourceFor(source).currency}, which you can change in the top bar.
          Every check is saved below.
        </p>

        <textarea
          rows={10}
          value={text}
          placeholder={PLACEHOLDER}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
        />

        <div className="filter-actions">
          <button
            className="primary"
            onClick={() => void runCheck()}
            disabled={running || !text.trim()}
          >
            {running ? "Checking…" : "Check against my collection"}
          </button>
          {/* The whole answer, not just the question: the totals, the cost and
              the shortfall lists below are all about the list being cleared, so
              leaving them up would attach them to whatever is typed next. Stays
              enabled while there is anything left to clear, so an emptied box
              never strands a result nothing can dismiss. The check itself stays
              saved; this only puts it away. */}
          <button
            className="subtle"
            onClick={() => {
              setText("");
              setResult(null);
              setError(null);
              if (checkId) navigate("/deck");
            }}
            disabled={!text && !result && !error}
          >
            Clear
          </button>
        </div>

        {error && (
          <div style={{ marginTop: "0.8rem" }}>
            <ErrorNotice message={error} />
          </div>
        )}
      </div>

      {running && !result && checkId && <Loading what="deck check" />}

      {result && check && (
        <div className="panel">
          <div className="between" style={{ alignItems: "center" }}>
            <CheckName
              key={check.id}
              name={check.name}
              onRename={(name) => change(check.id, { name })}
            />
            <OwnedToggle
              on={check.owned}
              onChange={(owned) => change(check.id, { owned })}
            />
          </div>
          <p className="muted" style={{ fontSize: "0.8rem", margin: "0.5rem 0 0" }}>
            {check.owned ? (
              <>
                Holding {copies(check.copies_held)} for this deck. Other deck checks
                don't count them as owned.
                {check.copies_held < check.total_needed &&
                  " The copies you don't own aren't held from anyone."}
              </>
            ) : (
              <>
                Built this deck? Turn this on and the copies it uses are held for
                it, so other deck checks no longer count them as owned. If two
                decks want the same copy, the one flagged first keeps it.
              </>
            )}
          </p>
        </div>
      )}

      {result && <Analysis result={result} />}

      <History
        checks={checks.data}
        loading={checks.loading}
        error={checks.error}
        openId={checkId ?? null}
        onChange={change}
        onDelete={remove}
      />
    </div>
  );
}

function Analysis({ result }: { result: DeckAnalysis }) {
  // Copies this deck would otherwise have counted, but another deck holds.
  const heldFromThis = result.cards.reduce(
    (sum, c) =>
      sum +
      Math.min(c.needed, c.owned) -
      Math.min(c.needed, c.owned - c.held_elsewhere),
    0,
  );

  return (
    <>
      <div className="tiles">
        <Tile
          value={result.total_needed}
          label="Cards the deck needs"
          note={`main ${result.zone_counts.main ?? 0} · extra ${
            result.zone_counts.extra ?? 0
          } · side ${result.zone_counts.side ?? 0}`}
        />
        <Tile
          value={result.total_owned}
          label="Already owned"
          note={
            heldFromThis > 0
              ? `Not counting ${copies(heldFromThis)} held by other decks`
              : "Any printing, condition or language"
          }
        />
        <Tile
          value={result.total_missing}
          label="Copies missing"
          note={`across ${result.distinct_missing} distinct cards`}
        />
      </div>

      <div className="panel">
        <div className="panel-title">Estimated cost of the missing cards</div>
        <div className="big-money">
          <Amount value={result.estimated_cost} />
        </div>
        <div className="notice estimate" style={{ marginTop: "0.7rem" }}>
          <strong>This is an estimate.</strong> {result.caveat}
        </div>
        {result.unresolved.length > 0 && (
          <div className="notice error" style={{ marginTop: "0.7rem" }}>
            <strong>{result.unresolved.length} line(s) matched no card</strong> and
            were left out of every total above:{" "}
            {result.unresolved.join(", ")}
          </div>
        )}
      </div>

      {result.total_missing > 0 && (
        <div className="panel">
          <div className="panel-title">Cards you still need</div>
          <ExportBlock
            label="As a ydke:// code"
            hint="Paste into EDOPro, or back into the box above."
            value={result.missing_ydke}
            rows={2}
          />
          <ExportBlock
            label="As a list"
            hint="One line per card, grouped by deck."
            value={result.missing_text}
            rows={Math.min(16, result.missing_text.split("\n").length)}
          />
          <p className="muted" style={{ fontSize: "0.78rem", margin: "0.6rem 0 0" }}>
            Only the copies you are short of are listed, not the whole deck.
            {heldFromThis > 0 && " Copies other decks are holding count as short."}
            {result.unresolved.length > 0 &&
              " Lines that matched no card are not in it either."}
          </p>
        </div>
      )}

      <div className="panel">
        <div className="panel-title">
          Card by card · detected format: {result.source_format}
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Card</th>
                <th>Zones</th>
                <th className="num">Needs</th>
                <th className="num">Owns</th>
                <th className="num">Missing</th>
                <th className="num">Each</th>
                <th className="num">Subtotal</th>
              </tr>
            </thead>
            <tbody>
              {result.cards.map((card) => (
                <tr key={card.passcode}>
                  <td>
                    <Link to={`/card/${card.passcode}`}>{card.name}</Link>
                  </td>
                  <td className="muted" style={{ fontSize: "0.78rem" }}>
                    {(["main", "extra", "side"] as const)
                      .filter((z) => card.zones[z])
                      .map((z) => `${z} ×${card.zones[z]}`)
                      .join(", ")}
                  </td>
                  <td className="num">{card.needed}</td>
                  <td className="num">
                    {card.owned - card.held_elsewhere}
                    {card.held_elsewhere > 0 && (
                      <div className="held-note" title={card.held_by.join(", ")}>
                        {card.held_elsewhere} held by {card.held_by.join(", ")}
                      </div>
                    )}
                  </td>
                  <td className="num">
                    {card.missing > 0 ? (
                      <span className="pill missing">{card.missing}</span>
                    ) : (
                      <span className="pill owned">complete</span>
                    )}
                  </td>
                  <td className="num">
                    {card.missing > 0 ? (
                      <Amount value={card.unit_price} />
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="num"><Amount value={card.subtotal} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function History({
  checks,
  loading,
  error,
  openId,
  onChange,
  onDelete,
}: {
  checks: DeckCheck[] | null;
  loading: boolean;
  error: string | null;
  openId: string | null;
  onChange: (id: string, patch: { owned: boolean }) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  async function act(id: string, action: () => Promise<void>) {
    setBusy(id);
    setFailure(null);
    try {
      await action();
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(null);
      setConfirming(null);
    }
  }

  const held = checks?.filter((c) => c.owned).length ?? 0;

  return (
    <div className="panel">
      <div className="panel-title">Deck checks</div>
      <div className="panel-subtitle">
        Every check you run is kept here. Turn on <strong>Owned</strong> for a deck
        you've built, and the copies it uses are held for it: other deck checks
        won't count them. If two decks want the same copy, the one flagged first
        keeps it.
        {held > 0 && ` ${held} of ${checks!.length} ${held === 1 ? "is" : "are"} holding copies.`}
      </div>

      {error && <ErrorNotice message={error} />}
      {failure && <ErrorNotice message={failure} />}
      {loading && !checks && <Loading what="deck checks" />}
      {checks && checks.length === 0 && (
        <p className="muted" style={{ fontSize: "0.85rem", margin: 0 }}>
          No deck checks yet. Check a list above and it will appear here.
        </p>
      )}

      {checks && checks.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Deck</th>
                <th>Last checked</th>
                <th className="num">Needs</th>
                <th className="num">Missing</th>
                <th>Owned</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {checks.map((c) => (
                <tr key={c.id} className={c.id === openId ? "current-row" : undefined}>
                  <td>
                    <Link to={`/deck/${c.id}`}>{c.name}</Link>
                    {c.id === openId && <span className="muted"> · open</span>}
                  </td>
                  <td className="muted" style={{ fontSize: "0.78rem", whiteSpace: "nowrap" }}>
                    {when(c.checked_at)}
                  </td>
                  <td className="num">{c.total_needed}</td>
                  <td className="num">
                    {c.total_missing > 0 ? (
                      <span className="pill missing">{c.total_missing}</span>
                    ) : (
                      <span className="pill owned">complete</span>
                    )}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <OwnedToggle
                      compact
                      on={c.owned}
                      disabled={busy === c.id}
                      onChange={(owned) => act(c.id, () => onChange(c.id, { owned }))}
                    />
                    {c.owned && (
                      <span className="muted" style={{ fontSize: "0.75rem" }}>
                        {" "}holds {c.copies_held}
                      </span>
                    )}
                  </td>
                  <td className="num">
                    {confirming === c.id ? (
                      <>
                        <button
                          className="danger"
                          disabled={busy === c.id}
                          onClick={() => void act(c.id, () => onDelete(c.id))}
                        >
                          {c.owned ? "Delete and free its copies?" : "Really delete?"}
                        </button>{" "}
                        <button className="subtle" onClick={() => setConfirming(null)}>
                          Keep
                        </button>
                      </>
                    ) : (
                      <button
                        className="danger subtle"
                        disabled={busy === c.id}
                        onClick={() => setConfirming(c.id)}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** "Owned for this deck": a pressed/unpressed button, not a checkbox, so it
 *  reads as the one action it is. */
function OwnedToggle({
  on,
  onChange,
  disabled,
  compact,
}: {
  on: boolean;
  onChange: (on: boolean) => void | Promise<void>;
  disabled?: boolean;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      className={`own-toggle${on ? " on" : ""}${compact ? " compact" : ""}`}
      aria-pressed={on}
      disabled={disabled || busy}
      onClick={async () => {
        setBusy(true);
        try {
          await onChange(!on);
        } finally {
          setBusy(false);
        }
      }}
    >
      <span className="own-mark" aria-hidden="true">{on ? "✓" : ""}</span>
      {compact ? (on ? "Owned" : "Not owned") : "Owned for this deck"}
    </button>
  );
}

function CheckName({
  name,
  onRename,
}: {
  name: string;
  onRename: (name: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const [failure, setFailure] = useState<string | null>(null);

  async function save() {
    const next = draft.trim();
    if (!next || next === name) {
      setEditing(false);
      setDraft(name);
      return;
    }
    try {
      await onRename(next);
      setEditing(false);
      setFailure(null);
    } catch (e) {
      setFailure((e as Error).message);
    }
  }

  if (!editing) {
    return (
      <div className="row">
        <h2 style={{ margin: 0 }}>{name}</h2>
        <button
          className="link"
          style={{ fontSize: "0.8rem" }}
          onClick={() => {
            setDraft(name);
            setEditing(true);
          }}
        >
          Rename
        </button>
      </div>
    );
  }
  return (
    <div className="row" style={{ flex: 1, minWidth: "16rem" }}>
      <input
        autoFocus
        aria-label="Deck check name"
        value={draft}
        maxLength={200}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") void save();
          if (e.key === "Escape") {
            setEditing(false);
            setDraft(name);
          }
        }}
        style={{ flex: 1, width: "auto" }}
      />
      <button className="primary" onClick={() => void save()} disabled={!draft.trim()}>
        Save
      </button>
      <button className="subtle" onClick={() => setEditing(false)}>
        Cancel
      </button>
      {failure && <ErrorNotice message={failure} />}
    </div>
  );
}

function ExportBlock({
  label,
  hint,
  value,
  rows,
}: {
  label: string;
  hint: string;
  value: string;
  rows: number;
}) {
  return (
    <div className="export-block">
      <div className="export-head">
        <span>
          {label} <span className="muted">· {hint}</span>
        </span>
        <CopyButton text={value} />
      </div>
      <textarea value={value} rows={rows} readOnly spellCheck={false} />
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
