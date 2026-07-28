import { NavLink, Route, Routes } from "react-router-dom";
import { getCollectionStatus } from "./api";
import EmptyState from "./components/EmptyState";
import { Loading } from "./components/common";
import { useAsync } from "./hooks";
import BrowsePage from "./pages/BrowsePage";
import CardPage from "./pages/CardPage";
import DeckPage from "./pages/DeckPage";
import StatsPage from "./pages/StatsPage";
import ValuationPage from "./pages/ValuationPage";

const LINKS = [
  { to: "/", label: "Browse", end: true },
  { to: "/stats", label: "Statistics", end: false },
  { to: "/valuation", label: "Valuation", end: false },
  { to: "/deck", label: "Deck check", end: false },
];

export default function App() {
  const { data: status, loading, reload } = useAsync(getCollectionStatus, []);

  return (
    <div className="app">
      <nav className="nav">
        <span className="nav-brand">YGO Collection Explorer</span>
        <div className="nav-links">
          {LINKS.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.end}>
              {link.label}
            </NavLink>
          ))}
        </div>
        {status?.has_collection && (
          <span className="nav-status">
            {status.collection_rows} rows · read-only
          </span>
        )}
      </nav>

      {loading ? (
        <Loading what="your collection" />
      ) : status && !status.has_collection ? (
        <EmptyState onLoaded={reload} />
      ) : (
        <Routes>
          <Route path="/" element={<BrowsePage />} />
          <Route path="/card/:passcode" element={<CardPage />} />
          <Route path="/stats" element={<StatsPage />} />
          <Route path="/valuation" element={<ValuationPage />} />
          <Route path="/deck" element={<DeckPage />} />
        </Routes>
      )}
    </div>
  );
}
