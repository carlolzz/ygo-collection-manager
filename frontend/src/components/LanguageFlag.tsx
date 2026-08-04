/** Flags for the export's language codes.
 *
 * Drawn as inline SVG rather than emoji on purpose: Windows ships no flag
 * glyphs, so 🇩🇪 renders there as the letters "DE" in a box — the one platform
 * where the emoji shortcut looks broken is the most common one.
 *
 * The column is free-form (see collection/schema.py), so anything unlisted
 * falls back to its code rather than disappearing. Note SP, not ES: that is the
 * code the scanner writes for Spanish.
 */

export const LANGUAGE_NAMES: Record<string, string> = {
  EN: "English",
  DE: "German",
  FR: "French",
  IT: "Italian",
  SP: "Spanish",
  PT: "Portuguese",
  JP: "Japanese",
  KR: "Korean",
  AE: "Asian-English",
};

/** A 3:2 field, so every flag below is drawn to the same box. */
function Flag({ children }: { children: React.ReactNode }) {
  return (
    <svg className="lang-flag" viewBox="0 0 3 2" preserveAspectRatio="none" aria-hidden="true">
      {children}
    </svg>
  );
}

/** Vertical thirds, left to right. */
function Vertical({ colors }: { colors: [string, string, string] }) {
  return (
    <Flag>
      {colors.map((fill, i) => (
        <rect key={i} x={i} y={0} width={1} height={2} fill={fill} />
      ))}
    </Flag>
  );
}

const FLAGS: Record<string, () => React.ReactElement> = {
  DE: () => (
    <Flag>
      <rect width="3" height="2" fill="#000" />
      <rect y="0.667" width="3" height="1.333" fill="#dd0000" />
      <rect y="1.333" width="3" height="0.667" fill="#ffce00" />
    </Flag>
  ),
  FR: () => <Vertical colors={["#002395", "#fff", "#ed2939"]} />,
  IT: () => <Vertical colors={["#009246", "#fff", "#ce2b37"]} />,
  SP: () => (
    <Flag>
      <rect width="3" height="2" fill="#aa151b" />
      <rect y="0.5" width="3" height="1" fill="#f1bf00" />
    </Flag>
  ),
  PT: () => (
    <Flag>
      <rect width="3" height="2" fill="#da291c" />
      <rect width="1.2" height="2" fill="#046a38" />
      <circle cx="1.2" cy="1" r="0.42" fill="#ffe900" />
      <circle cx="1.2" cy="1" r="0.28" fill="#da291c" />
    </Flag>
  ),
  JP: () => (
    <Flag>
      <rect width="3" height="2" fill="#fff" />
      <circle cx="1.5" cy="1" r="0.6" fill="#bc002d" />
    </Flag>
  ),
  KR: () => (
    // The taegeuk without its trigrams — at 17 pixels wide they would be four
    // grey smudges, and the red-over-blue disc is what makes the flag readable.
    // The blue half is the disc's lower S: two small arcs, then the big one back.
    <Flag>
      <rect width="3" height="2" fill="#fff" />
      <circle cx="1.5" cy="1" r="0.55" fill="#cd2e3a" />
      <path
        d="M0.95 1 a0.275 0.275 0 0 1 0.55 0 a0.275 0.275 0 0 0 0.55 0 a0.55 0.55 0 0 1 -1.1 0"
        fill="#0047a0"
      />
    </Flag>
  ),
  EN: () => (
    <Flag>
      <rect width="3" height="2" fill="#012169" />
      <path d="M0 0 L3 2 M3 0 L0 2" stroke="#fff" strokeWidth="0.4" />
      <path d="M0 0 L3 2 M3 0 L0 2" stroke="#c8102e" strokeWidth="0.24" />
      <path d="M1.5 0 V2 M0 1 H3" stroke="#fff" strokeWidth="0.66" />
      <path d="M1.5 0 V2 M0 1 H3" stroke="#c8102e" strokeWidth="0.4" />
    </Flag>
  ),
};

export function languageName(code: string) {
  return LANGUAGE_NAMES[code] ?? code;
}

/** One flag, or the bare code when there is no flag to draw for it. */
export default function LanguageFlag({ code }: { code: string }) {
  const draw = FLAGS[code];
  const title = LANGUAGE_NAMES[code] ? `${LANGUAGE_NAMES[code]} (${code})` : code;
  return (
    <span className="lang" title={title}>
      {draw ? draw() : <span className="lang-chip">{code}</span>}
      <span className="sr-only">{title}</span>
    </span>
  );
}

/** A card's languages, capped so a well-travelled card cannot flood the tile. */
export function LanguageFlags({
  codes,
  max = 3,
  className,
}: {
  codes: string[];
  max?: number;
  className?: string;
}) {
  if (codes.length === 0) return null;
  const shown = codes.slice(0, max);
  const rest = codes.length - shown.length;
  return (
    <span className={className ? `lang-flags ${className}` : "lang-flags"}>
      {shown.map((code) => (
        <LanguageFlag key={code} code={code} />
      ))}
      {rest > 0 && <span className="lang-chip">+{rest}</span>}
    </span>
  );
}
