import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { analyzeDeck } from "../api";
import { Amount, ErrorNotice } from "../components/common";
import { useAction } from "../hooks";
import { sourceFor, usePriceSource } from "../priceSource";

const PLACEHOLDER = `Paste a ydke:// code, a .ydk file, or a plain list:

Main Deck:
3 Sabersaurus
2 Rescue Rabbit
1 Heavy Storm

Side Deck:
2 Maxx "C"`;

export default function DeckPage() {
  const [text, setText] = useState("");
  const { source } = usePriceSource();
  const analysis = useAction(analyzeDeck);
  const result = analysis.data;

  // Costs are in the source's currency, so a change invalidates the answer
  // rather than merely restating it.
  const { setData } = analysis;
  useEffect(() => setData(null), [source, setData]);

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
            onClick={() => analysis.trigger(text, source)}
            disabled={analysis.running || !text.trim()}
          >
            {analysis.running ? "Checking…" : "Check against my collection"}
          </button>
          <button className="subtle" onClick={() => setText("")} disabled={!text}>
            Clear
          </button>
        </div>

        {analysis.error && (
          <div style={{ marginTop: "0.8rem" }}>
            <ErrorNotice message={analysis.error} />
          </div>
        )}
      </div>

      {result && (
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
              note="Any printing, condition or language"
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
                      <td className="num">{card.owned}</td>
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
