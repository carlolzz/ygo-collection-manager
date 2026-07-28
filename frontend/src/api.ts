/** Typed access to the read API.
 *
 * Note what is *not* here: no polling, no prefetch, no price lookup on mount.
 * Prices are only ever requested by `valueCollection`, `valueCard` and
 * `analyzeDeck`, each of which is wired to a button.
 */

import type {
  CardDetail,
  CardPage,
  CatalogueStatus,
  CollectionStatus,
  DeckAnalysis,
  FilterOptions,
  RefineJob,
  Stats,
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

const post = <T>(path: string, body?: unknown): Promise<T> =>
  request<T>(path, {
    method: "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const listCards = (query: string) =>
  request<CardPage>(`/cards${query ? `?${query}` : ""}`);

export const getCard = (passcode: string) =>
  request<CardDetail>(`/cards/${encodeURIComponent(passcode)}`);

export const getStats = () => request<Stats>("/stats");
export const getFilterOptions = () => request<FilterOptions>("/meta/filters");
export const getCatalogueStatus = () => request<CatalogueStatus>("/catalogue/status");
export const getCollectionStatus = () => request<CollectionStatus>("/collection/status");

export const refreshCatalogue = (force = false) =>
  post<CatalogueStatus>(`/catalogue/refresh?force=${force}`);

export const valueCollection = (sourceField = "tcgplayer_price") =>
  post<Valuation>(`/valuation/collection?source_field=${sourceField}`);

export const valueCard = (passcode: string, sourceField = "tcgplayer_price") =>
  post<Valuation>(
    `/valuation/card/${encodeURIComponent(passcode)}?source_field=${sourceField}`,
  );

export const startRefinement = () => post<RefineJob>("/valuation/refine");
export const getRefinement = (id: string) => request<RefineJob>(`/valuation/refine/${id}`);
export const cancelRefinement = (id: string) =>
  request<RefineJob>(`/valuation/refine/${id}`, { method: "DELETE" });

export const analyzeDeck = (text: string) =>
  post<DeckAnalysis>("/deck/analyze", { text });

export async function uploadCollection(file: File): Promise<CollectionStatus> {
  const form = new FormData();
  form.append("file", file);
  return request<CollectionStatus>("/collection/upload", {
    method: "POST",
    body: form,
  });
}

/** Art always comes from our own cache — never hotlinked from YGOPRODeck. */
export const imageUrl = (passcode: string) =>
  `/api/images/${encodeURIComponent(passcode)}`;
