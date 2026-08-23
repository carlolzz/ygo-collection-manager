/** The four things that describe a copy, and the key that identifies a row.
 *
 * Shared by the add and edit dialogs. They ask different questions — one is
 * "what am I putting in", the other "what did I get wrong" — but a condition is
 * a condition, and the two must offer exactly the same set of answers or a row
 * saved by one becomes unreachable to the other.
 */

import type { CataloguePrinting, EntryKey, OwnedRow } from "../types";
import LanguageFlag, { LANGUAGE_NAMES } from "./LanguageFlag";
import { formatCondition } from "./common";

/** Cardmarket's grades, best first — the order in collection/schema.py. */
export const CONDITIONS = [
  "MINT",
  "NEAR_MINT",
  "EXCELLENT",
  "GOOD",
  "LIGHT_PLAYED",
  "PLAYED",
  "POOR",
] as const;

/** Cardmarket's own abbreviations, from help.cardmarket.com/en/CardCondition.
 *
 * Kept beside the grade list rather than in a display module: the two have to
 * cover exactly the same set, and a grade added to one and not the other is a
 * badge reading `LIGHT_PLAYED` in a box sized for two letters.
 */
export const CONDITION_ABBR: Record<string, string> = {
  MINT: "M",
  NEAR_MINT: "NM",
  EXCELLENT: "EX",
  GOOD: "GD",
  LIGHT_PLAYED: "LP",
  PLAYED: "PL",
  POOR: "PO",
};

/** A grade as Cardmarket shows it: a small colour-coded rectangle.
 *
 * The colour is the information — a green-to-red ramp read at a glance down a
 * column — so the full name goes in the title and the accessible label rather
 * than being spelled out in a cell it would dominate.
 *
 * An unlisted grade falls back to a neutral badge carrying its raw code, for
 * the reason LanguageFlag falls back to a bare language code: the column is
 * whatever the CSV says it is, and an unrecognized value must not vanish.
 */
export function ConditionBadge({ condition }: { condition: string }) {
  const abbr: string | undefined = CONDITION_ABBR[condition];
  // formatCondition lowercases for prose; a tooltip reads as a proper name.
  const name = formatCondition(condition).replace(/\b\w/g, (c) => c.toUpperCase());
  return (
    <span
      className={abbr ? `cond-badge cond-${abbr.toLowerCase()}` : "cond-badge"}
      title={name}
    >
      {abbr ?? condition}
      <span className="sr-only"> {name}</span>
    </span>
  );
}

export const EDITIONS: { value: string; label: string }[] = [
  { value: "FIRST", label: "1st Edition" },
  { value: "UNLIMITED", label: "Unlimited" },
  { value: "LIMITED", label: "Limited Edition" },
];

export function printingLabel(p: CataloguePrinting) {
  // Rarity second, ahead of the set name: a long set name is what gets clipped,
  // and the rarity is the part that decides which copy this is.
  return [p.set_code, p.set_rarity, p.set_name].filter(Boolean).join(" · ");
}

/** The natural key as one comparable string, exactly as the server groups on it.
 *
 * Used to tell rows apart in the browser — folding identical copies before a
 * save, spotting that an edit is about to land on a row already owned. The
 * server does the same grouping over the file and is the authority; this only
 * has to agree with it about which rows are the same row.
 */
export function entryKeyOf(key: EntryKey) {
  return [
    key.passcode,
    key.set_code ?? "",
    key.set_name ?? "",
    key.rarity ?? "",
    key.condition,
    key.edition,
    key.language,
  ].join(" ");
}

/** An owned row's identity, for the endpoints that address one.
 *
 * Copied field by field rather than spread, so the timestamps and the quantity
 * cannot ride along into a request whose whole job is to say *which* row.
 * The values are passed through untouched: the server matches them against the
 * file verbatim.
 */
export const keyFor = (passcode: string, row: OwnedRow): EntryKey => ({
  passcode,
  set_code: row.set_code,
  set_name: row.set_name,
  rarity: row.rarity,
  condition: row.condition,
  edition: row.edition,
  language: row.language,
});

interface FieldProps {
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}

export function ConditionSelect({ value, disabled, onChange }: FieldProps) {
  return (
    <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
      {CONDITIONS.map((c) => (
        <option key={c} value={c}>
          {formatCondition(c)}
        </option>
      ))}
    </select>
  );
}

export function EditionSelect({ value, disabled, onChange }: FieldProps) {
  return (
    <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
      {EDITIONS.map((e) => (
        <option key={e.value} value={e.value}>
          {e.label}
        </option>
      ))}
    </select>
  );
}

export function LanguageSelect({ value, disabled, onChange }: FieldProps) {
  return (
    <span className="lang-cell">
      <LanguageFlag code={value} />
      <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {/* A code the list has never heard of is still a valid language by
            contract — an imported row can carry one, and it must not be
            silently swapped for whatever happens to be first. */}
        {!(value in LANGUAGE_NAMES) && <option value={value}>{value}</option>}
        {Object.entries(LANGUAGE_NAMES).map(([code, label]) => (
          <option key={code} value={code}>
            {code} · {label}
          </option>
        ))}
      </select>
    </span>
  );
}
