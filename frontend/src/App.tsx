import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { getCatalogueStatus, getCollectionStatus } from "./api";
import CatalogueBanner from "./components/CatalogueBanner";
import EmptyState from "./components/EmptyState";
import UploadButton from "./components/UploadButton";
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
  const catalogue = useAsync(getCatalogueStatus, []);
  // Bumped when a new export is loaded. It keys the routes below, so every page
  // remounts and refetches instead of showing the previous CSV's cards.
  const [dataVersion, setDataVersion] = useState(0);

  function onCollectionLoaded() {
    reload();
    catalogue.reload();
    setDataVersion((v) => v + 1);
  }

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
          <div className="nav-actions">
            <span className="nav-status">
              {status.collection_rows} rows · read-only
            </span>
            <UploadButton
              onLoaded={onCollectionLoaded}
              label="Load CSV"
              className="subtle"
              hasCollection
            />
          </div>
        )}
      </nav>

      {loading ? (
        <Loading what="your collection" />
      ) : status && !status.has_collection ? (
        <EmptyState onLoaded={onCollectionLoaded} />
      ) : (
        <>
          <CatalogueBanner
            status={catalogue.data}
            onRefreshed={() => {
              catalogue.reload();
              reload();
            }}
          />
          <Routes key={dataVersion}>
            <Route path="/" element={<BrowsePage />} />
            <Route path="/card/:passcode" element={<CardPage />} />
            <Route path="/stats" element={<StatsPage />} />
            <Route path="/valuation" element={<ValuationPage />} />
            <Route path="/deck" element={<DeckPage />} />
          </Routes>
        </>
      )}
    </div>
  );
}
