/** Typed access to the read API.
 *
 * Note what is *not* here: no polling, no prefetch, no price lookup on mount.
 * Prices are only ever requested by `valueCollection`, `valueCard` and
 * `analyzeDeck`, each of which is wired to a button.
 */

import type {
  CardDetail,
  CardPage,
  CatalogueCard,
  CatalogueJob,
  CataloguePrinting,
  CatalogueStatus,
  CollectionStatus,
  DeckAnalysis,
  DeckCheck,
  EntryKey,
  FilterOptions,
  NewEntry,
  RefineJob,
  Stats,
  UploadPreview,
  Valuation,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* a non-JSON error body is not worth a second failure */
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

const send = <T>(method: string, path: string, body?: unknown): Promise<T> =>
  request<T>(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

const post = <T>(path: string, body?: unknown): Promise<T> => send<T>("POST", path, body);

export const listCards = (query: string) =>
  request<CardPage>(`/cards${query ? `?${query}` : ""}`);

export const getCard = (passcode: string) =>
  request<CardDetail>(`/cards/${encodeURIComponent(passcode)}`);

export const getStats = () => request<Stats>("/stats");
export const getFilterOptions = () => request<FilterOptions>("/meta/filters");
export const getCatalogueStatus = () => request<CatalogueStatus>("/catalogue/status");
export const getCollectionStatus = () => request<CollectionStatus>("/collection/status");

/** Start the card-data download. Returns as soon as it is under way — forty
 *  megabytes is too long to hold a request open with nothing to report — so the
 *  caller polls `getCatalogueRefresh` for the bytes and the time left. */
export const startCatalogueRefresh = (force = false) =>
  post<CatalogueJob>(`/catalogue/refresh?force=${force}`);

export const getCatalogueRefresh = (id: string) =>
  request<CatalogueJob>(`/catalogue/refresh/${id}`);

// `sourceField` is required on purpose: the default lives in the server's
// config and nowhere else, so the two can never drift apart.
export const valueCollection = (sourceField: string) =>
  post<Valuation>(
    `/valuation/collection?source_field=${encodeURIComponent(sourceField)}`,
  );

export const valueCard = (passcode: string, sourceField: string) =>
  post<Valuation>(
    `/valuation/card/${encodeURIComponent(passcode)}` +
      `?source_field=${encodeURIComponent(sourceField)}`,
  );

export const startRefinement = () => post<RefineJob>("/valuation/refine");
export const getRefinement = (id: string) => request<RefineJob>(`/valuation/refine/${id}`);
export const cancelRefinement = (id: string) =>
  request<RefineJob>(`/valuation/refine/${id}`, { method: "DELETE" });

/** Checks a list and saves the check. The same list again updates its entry. */
export const analyzeDeck = (text: string, sourceField: string) =>
  post<DeckAnalysis>("/deck/analyze", { text, source_field: sourceField });

export const listDeckChecks = () => request<DeckCheck[]>("/deck/checks");

/** A saved check, compared against the collection as it is now. */
export const getDeckCheck = (id: string, sourceField: string) =>
  request<DeckAnalysis>(
    `/deck/checks/${encodeURIComponent(id)}?source_field=${encodeURIComponent(sourceField)}`,
  );

export const updateDeckCheck = (id: string, patch: { name?: string; owned?: boolean }) =>
  send<DeckCheck>("PATCH", `/deck/checks/${encodeURIComponent(id)}`, patch);

/** Answers 204, so not through `request`, which would try to parse a body. */
export async function deleteDeckCheck(id: string): Promise<void> {
  const response = await fetch(`/api/deck/checks/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new ApiError(`${response.status} ${response.statusText}`, response.status);
}

/** What to do with rows the loaded collection already has. */
export type UploadMode = "replace" | "merge_sum" | "merge_keep";

/** Ask what an export would do, without doing it. Changes nothing server-side. */
export async function previewCollection(file: File): Promise<UploadPreview> {
  const form = new FormData();
  form.append("file", file);
  return request<UploadPreview>("/collection/preview", { method: "POST", body: form });
}

export async function uploadCollection(
  file: File,
  mode: UploadMode = "replace",
): Promise<CollectionStatus> {
  const form = new FormData();
  form.append("file", file);
  form.append("mode", mode);
  return request<CollectionStatus>("/collection/upload", {
    method: "POST",
    body: form,
  });
}

/** Search the cached card data — every card, not only the owned ones.
 *
 * Served from the local dump, so this is free to call on every keystroke: it is
 * a parquet scan, not a request to YGOPRODeck.
 *
 * `language` scopes the *name* search to that language and nothing else, so a
 * card the localized dump does not cover is not findable while it is set. All
 * digits is matched as a passcode, which has no language to scope.
 */
export const searchCatalogue = (q: string, language?: string, limit = 25) =>
  request<CatalogueCard[]>(
    `/catalogue/cards?q=${encodeURIComponent(q)}&limit=${limit}` +
      (language ? `&language=${encodeURIComponent(language)}` : ""),
  );

/** Every printing the card data lists for a card, with the owned ones flagged. */
export const getCataloguePrintings = (passcode: string) =>
  request<CataloguePrinting[]>(
    `/catalogue/cards/${encodeURIComponent(passcode)}/printings`,
  );

/** Add rows to the collection.
 *
 * Rows agreeing on printing, condition, edition and language are folded into
 * one on the server — including with rows already owned, which are incremented
 * rather than duplicated. The whole request is one save: a single invalid row
 * rejects all of it.
 */
export const addEntries = (rows: NewEntry[]) =>
  post<CollectionStatus>("/collection/entries", { rows });

/** Replace one row with another.
 *
 * The old row is removed and the new one folded back in, which is the scanner's
 * own rule: editing a row into a printing, condition, edition and language
 * already owned merges into that row rather than making a second one. Setting a
 * quantity sets it — the old row is gone before the fold, so it is not added to.
 */
export const editEntry = (key: EntryKey, row: NewEntry) =>
  send<CollectionStatus>("PATCH", "/collection/entries", { key, row });

/** Remove one row. The export it is still in stays on disk. */
export const deleteEntry = (key: EntryKey) =>
  send<CollectionStatus>("DELETE", "/collection/entries", { keys: [key] });

/** The loaded export, served as a file. A plain URL, like `imageUrl` — the
 *  browser does the downloading, so there is no Blob and no JS in the path. */
export const EXPORT_URL = "/api/collection/export";

/** Art always comes from our own cache — never hotlinked from YGOPRODeck. */
export const imageUrl = (passcode: string) =>
  `/api/images/${encodeURIComponent(passcode)}`;
