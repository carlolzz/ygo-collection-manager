import { useCallback, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { EXPORT_URL, getCatalogueStatus, getCollectionStatus } from "./api";
import { CollectionReloadProvider } from "./collectionReload";
import { DeclinedLanguagesProvider } from "./declinedLanguages";
import AddCardButton from "./components/AddCardButton";
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
import { PriceSourceProvider, PriceSourceSelect } from "./priceSource";

const LINKS = [
  { to: "/", label: "Browse", end: true },
  { to: "/stats", label: "Statistics", end: false },
  { to: "/valuation", label: "Valuation", end: false },
  { to: "/deck", label: "Deck check", end: false },
];

export default function App() {
  const { data: status, loading, reload } = useAsync(getCollectionStatus, []);
  const catalogue = useAsync(getCatalogueStatus, []);
  const reloadCatalogue = catalogue.reload;
  // Bumped when a new export is loaded. It keys the routes below, so every page
  // remounts and refetches instead of showing the previous CSV's cards.
  const [dataVersion, setDataVersion] = useState(0);

  // Stable, because it is handed to a context every page below can call.
  const onCollectionLoaded = useCallback(() => {
    reload();
    reloadCatalogue();
    setDataVersion((v) => v + 1);
  }, [reload, reloadCatalogue]);

  return (
    <PriceSourceProvider>
      {/* Above both consumers: the banner has to disappear when the card picker
          turns a language back on, and vice versa. */}
      <DeclinedLanguagesProvider>
        <CollectionReloadProvider onReload={onCollectionLoaded}>
          <div className="app">
            <nav className="nav">
              <span className="nav-brand">YGO Collection Manager</span>
              <div className="nav-links">
                {LINKS.map((link) => (
                  <NavLink key={link.to} to={link.to} end={link.end}>
                    {link.label}
                  </NavLink>
                ))}
              </div>
              {status?.has_collection && (
                <div className="nav-actions">
                  <span className="nav-status">{status.collection_rows} rows</span>
                  {/* Lives here, not on the valuation page: it decides the currency
                      of the deck check and the card page too. */}
                  <PriceSourceSelect />
                  {/* An anchor, not a button: middle-click and "save link as" work,
                      and no JavaScript stands between the click and the file. */}
                  <a
                    className="button subtle"
                    href={EXPORT_URL}
                    download
                    title="Download the loaded export, exactly as it is on disk"
                  >
                    Download CSV
                  </a>
                  <AddCardButton onAdded={onCollectionLoaded} label="Add card" className="subtle" />
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
                    reloadCatalogue();
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
        </CollectionReloadProvider>
      </DeclinedLanguagesProvider>
    </PriceSourceProvider>
  );
}
