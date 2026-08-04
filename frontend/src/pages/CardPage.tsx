import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { getCard, imageUrl, valueCard } from "../api";
import { Amount, ErrorNotice, Loading, formatCondition } from "../components/common";
import LanguageFlag from "../components/LanguageFlag";
import { useAction, useAsync } from "../hooks";
import { usePriceSource } from "../priceSource";

export default function CardPage() {
  const { passcode = "" } = useParams();
  const { source } = usePriceSource();
  const { data: card, error, loading } = useAsync(() => getCard(passcode), [passcode]);
  // A price only ever appears because this button was pressed.
  const valuation = useAction(valueCard);

  // Drop a figure priced in a currency the user has since moved off.
  const { setData } = valuation;
  useEffect(() => setData(null), [source, setData]);

  if (loading) return <Loading what="card" />;
  if (error) return <ErrorNotice message={error} />;
  if (!card) return null;

  const stats: [string, string | number | null][] = [
    ["Type", card.type],
    ["Attribute", card.attribute],
    ["Race", card.race],
    ["Level", card.level],
    ["ATK", card.atk],
    ["DEF", card.defense],
    ["Archetype", card.archetype],
  ];

  return (
    <div className="stack">
      <Link to="/" className="muted">← Back to the collection</Link>

      <div className="grid-2">
        <div>
          <img
            className="card-art"
            src={imageUrl(card.passcode)}
            alt={card.name}
            style={{ borderRadius: "var(--radius)", maxWidth: 340 }}
          />
        </div>

        <div className="stack">
          <div>
            <h1>{card.name}</h1>
            <div className="muted">
              Passcode {card.passcode} · {card.total_copies}{" "}
              {card.total_copies === 1 ? "copy" : "copies"} across {card.row_count}{" "}
              {card.row_count === 1 ? "entry" : "entries"}
            </div>
          </div>

          {!card.in_catalogue && (
            <div className="notice">
              This card is not in the cached YGOPRODeck dump, so its stats and text
              are unknown. What you own is still recorded below.
            </div>
          )}

          {card.in_catalogue && (
            <div className="panel">
              <div className="panel-title">Card</div>
              <table>
                <tbody>
                  {stats
                    .filter(([, value]) => value !== null && value !== undefined)
                    .map(([label, value]) => (
                      <tr key={label}>
                        <td className="muted" style={{ width: "35%" }}>{label}</td>
                        <td>{value}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
              {card.description && (
                <p style={{ fontSize: "0.86rem", marginBottom: 0 }}>{card.description}</p>
              )}
            </div>
          )}

          <div className="panel">
            <div className="between">
              <div className="panel-title" style={{ marginBottom: 0 }}>Value</div>
              <button
                className="primary"
                onClick={() => valuation.trigger(card.passcode, source)}
                disabled={valuation.running}
              >
                {valuation.running ? "Calculating…" : "Calculate value"}
              </button>
            </div>

            {valuation.error && (
              <div style={{ marginTop: "0.8rem" }}>
                <ErrorNotice message={valuation.error} />
              </div>
            )}

            {valuation.data && (
              <div style={{ marginTop: "0.8rem" }}>
                <div className="big-money">
                  <Amount value={valuation.data.total} />
                </div>
                <div className="notice estimate" style={{ marginTop: "0.6rem" }}>
                  {valuation.data.caveat}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-title">
          What you own — {card.total_copies} copies by condition, edition and language
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th className="num">Qty</th>
                <th>Condition</th>
                <th>Edition</th>
                <th>Lang</th>
                <th>Printing</th>
                <th>Rarity</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {card.rows.map((row, i) => (
                <tr key={i}>
                  <td className="num">{row.quantity}</td>
                  <td>{formatCondition(row.condition)}</td>
                  <td>{row.edition.toLowerCase()}</td>
                  <td className="lang-cell">
                    <LanguageFlag code={row.language} /> {row.language}
                  </td>
                  <td>
                    {row.set_code ? (
                      <>
                        {row.set_code}{" "}
                        <span className="muted">{row.set_name}</span>
                      </>
                    ) : (
                      <span className="muted">no printing recorded</span>
                    )}
                  </td>
                  <td>{row.rarity ?? <span className="muted">—</span>}</td>
                  <td className="muted">{row.notes ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {card.printings.length > 0 && (
        <div className="panel">
          <div className="panel-title">
            Every printing of this card ({card.printings.filter((p) => p.owned).length}{" "}
            owned of {card.printings.length})
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Set code</th>
                  <th>Set</th>
                  <th>Rarity</th>
                  {/* USD whatever the chosen source: there is no per-printing
                      price in any other currency, at any grain. */}
                  <th className="num">Printing price (USD)</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {card.printings.map((printing) => (
                  <tr key={printing.set_code ?? Math.random()}>
                    <td>{printing.set_code}</td>
                    <td>{printing.set_name}</td>
                    <td>{printing.set_rarity}</td>
                    <td className="num">
                      {printing.set_price_usd != null ? (
                        printing.set_price_usd.toFixed(2)
                      ) : (
                        <span className="muted">no price</span>
                      )}
                    </td>
                    <td>
                      {printing.owned && <span className="pill owned">owned</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
