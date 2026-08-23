/** Languages whose name index this browser has been told not to ask about.
 *
 * A configured language is a ~19 MB download, and the app has no way of knowing
 * whether the person in front of it owns any cards printed in it. Someone handed
 * a copy of this who only collects in English should be able to say so once and
 * stop being asked, rather than being shown a banner they can only ever act on
 * or ignore.
 *
 * Purely a display preference. The server keeps reporting every configured
 * language in `search_languages`, and declining one downloads nothing, deletes
 * nothing, and stops nothing from being downloaded later — it only silences the
 * prompt and hides an option that could not be selected anyway.
 */

import { createContext, useContext, useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "ygo.declined_languages";

/** A set of codes rather than an Italian-shaped boolean: CATALOGUE_LANGUAGES is
 *  a tuple on the server, and it is allowed to grow. */
function read(): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    // A hand-edited key must not put anything odd into a language comparison.
    if (Array.isArray(parsed)) return parsed.filter((c) => typeof c === "string");
  } catch {
    /* absent, unparseable, or localStorage throwing outright in a privacy mode */
  }
  return [];
}

interface Store {
  declined: Set<string>;
  decline: (codes: string[]) => void;
  restore: (code: string) => void;
}

const Context = createContext<Store>({
  declined: new Set(),
  decline: () => {},
  restore: () => {},
});

export function DeclinedLanguagesProvider({ children }: { children: React.ReactNode }) {
  const [codes, setCodes] = useState<string[]>(read);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(codes));
    } catch {
      /* the choice still holds for this session */
    }
  }, [codes]);

  const value = useMemo<Store>(
    () => ({
      declined: new Set(codes),
      decline: (added) => setCodes((current) => [...new Set([...current, ...added])]),
      restore: (code) => setCodes((current) => current.filter((c) => c !== code)),
    }),
    [codes],
  );

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export const useDeclinedLanguages = () => useContext(Context);
