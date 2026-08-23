/** Mirrors the FastAPI response models in src/ygo_explorer/api/models.py.
 *
 * Count fields keep the API's naming deliberately: there is no `count`, because
 * "how many copies" and "how many distinct cards" are different numbers and a
 * label that hides which is which is the easiest bug to ship here.
 */

export interface Money {
  /** A decimal string, never a float — cents must not round in transit. */
  amount: string;
  currency: string;
}

export interface CardSummary {
  passcode: string;
  name: string;
  in_catalogue: boolean;
  type: string | null;
  frame_type: string | null;
  attribute: string | null;
  race: string | null;
  archetype: string | null;
  atk: number | null;
  defense: number | null;
  level: number | null;
  source_image_url: string | null;
  total_copies: number;
  row_count: number;
  printing_count: number;
  first_acquired_at: string | null;
  /** Every distinct language owned, sorted. Free-form, so not a union type. */
  languages: string[];
}

export interface CardPage {
  items: CardSummary[];
  total_cards: number;
  total_copies: number;
  limit: number;
  offset: number;
}

export interface OwnedRow {
  set_code: string | null;
  set_name: string | null;
  rarity: string | null;
  condition: string;
  edition: string;
  language: string;
  quantity: number;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CataloguePrinting {
  set_code: string | null;
  set_name: string | null;
  set_rarity: string | null;
  set_price_usd: number | null;
  owned: boolean;
}

/** A card the cached dump knows, owned or not. What the card picker offers. */
export interface CatalogueCard {
  passcode: string;
  name: string;
  type: string | null;
  printing_count: number;
  /** Copies of this card already held, counted per card rather than per passcode. */
  owned_copies: number;
  /** The name that matched, when it was not the English one. Never stored. */
  matched_name: string | null;
  matched_language: string | null;
}

/** One row on its way in: a stack of copies that agree on every detail.
 *
 * Deliberately not `OwnedRow`: the timestamps are the server's to stamp, and
 * conflating "what I am asking for" with "what is on file" is how a client ends
 * up inventing a created_at.
 */
export interface NewEntry {
  passcode: string;
  name: string;
  set_code: string | null;
  set_name: string | null;
  rarity: string | null;
  condition: string;
  edition: string;
  language: string;
  quantity: number;
  notes: string | null;
}

/** Which row, out of everything owned — the server's seven-column natural key.
 *
 * There is no row id in the export contract, so this *is* a row's identity. The
 * values must be echoed back exactly as the API served them: the server matches
 * them against the file verbatim, and a client that tidied them up would fail to
 * find a row it is looking straight at.
 */
export interface EntryKey {
  passcode: string;
  set_code: string | null;
  set_name: string | null;
  rarity: string | null;
  condition: string;
  edition: string;
  language: string;
}

export interface CardDetail extends CardSummary {
  description: string | null;
  rows: OwnedRow[];
  printings: CataloguePrinting[];
}

export interface Bucket {
  key: string | null;
  total_copies: number;
  distinct_cards: number;
}

export interface TimeBucket {
  period: string;
  total_copies: number;
  distinct_cards: number;
}

export interface Stats {
  total_copies: number;
  distinct_cards: number;
  collection_rows: number;
  sets_represented: number;
  copies_without_printing: number;
  by_condition: Bucket[];
  by_edition: Bucket[];
  by_language: Bucket[];
  by_type: Bucket[];
  by_attribute: Bucket[];
  by_archetype: Bucket[];
  by_set: Bucket[];
  acquisitions_by_month: TimeBucket[];
  most_held: CardSummary[];
}

export interface FilterOptions {
  condition: string[];
  edition: string[];
  language: string[];
  rarity: string[];
  set_name: string[];
  type: string[];
  frame_type: string[];
  attribute: string[];
  /** The raw upstream column, which mixes all three taxonomies below. */
  race: string[];
  monster_type: string[];
  spell_type: string[];
  trap_type: string[];
  archetype: string[];
  level_min: number | null;
  level_max: number | null;
}

export interface CatalogueStatus {
  fetched_at: string | null;
  age_days: number | null;
  /** Languages the picker can be searched in besides English. */
  languages: string[];
  catalogue_cards: number;
  catalogue_passcodes: number;
  collection_rows: number;
  matched_rows: number;
  unmatched_rows: number;
  unmatched_passcodes: number;
  message: string;
}

export interface CollectionStatus {
  has_collection: boolean;
  csv_path: string | null;
  collection_rows: number;
  message: string;
}

/** What an upload would do to the loaded collection, counted before it does it.
 *
 * "Overlapping" means the same printing in the same condition, edition and
 * language — the natural key — not merely the same card.
 */
export interface UploadPreview {
  has_collection: boolean;
  current_rows: number;
  incoming_rows: number;
  overlapping_rows: number;
  new_rows: number;
}

export interface ValuedRow {
  passcode: string;
  name: string;
  set_code: string | null;
  set_name: string | null;
  rarity: string | null;
  condition: string;
  edition: string;
  language: string;
  quantity: number;
  basis: "per_printing" | "per_passcode" | "unpriced";
  unit_price: Money | null;
  multiplier: string;
  subtotal: Money | null;
}

export interface Valuation {
  total: Money;
  currency: string;
  provider: string;
  source_field: string;
  is_estimate: boolean;
  caveat: string;
  per_printing_rows: number;
  per_passcode_rows: number;
  unpriced_rows: number;
  unpriced_copies: number;
  price_data_age_days: number | null;
  rows: ValuedRow[];
}

export interface RefineJob {
  id: string;
  status: "pending" | "running" | "cancelled" | "finished" | "error";
  done: number;
  total: number;
  current_set_code: string | null;
  refined: number;
  unavailable: number;
  failed: number;
  skipped_fresh: number;
  errors: string[];
}

export interface DeckCard {
  passcode: string;
  name: string;
  needed: number;
  owned: number;
  missing: number;
  zones: Record<string, number>;
  unit_price: Money | null;
  subtotal: Money | null;
}

export interface DeckAnalysis {
  source_format: "ydke" | "ydk" | "plaintext";
  currency: string;
  zone_counts: Record<string, number>;
  total_needed: number;
  total_owned: number;
  total_missing: number;
  distinct_missing: number;
  unpriced_missing_cards: number;
  estimated_cost: Money | null;
  caveat: string;
  unresolved: string[];
  missing_ydke: string;
  missing_text: string;
  cards: DeckCard[];
}
