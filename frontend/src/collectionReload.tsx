/** "The collection changed" — the one signal every write sends.
 *
 * The nav already knows how to react to it: reload the status, and bump the key
 * on the routes so every page refetches instead of showing the previous CSV's
 * cards. What was missing is a way for a page *inside* those routes to say so,
 * which editing a row from the card page needs.
 *
 * A context rather than prop-drilling because the callback is the same one for
 * everybody and passing it through Routes would mean threading it through pages
 * that never write.
 */

import { createContext, useContext } from "react";

const Context = createContext<() => void>(() => {});

export function CollectionReloadProvider({
  onReload,
  children,
}: {
  onReload: () => void;
  children: React.ReactNode;
}) {
  return <Context.Provider value={onReload}>{children}</Context.Provider>;
}

/** Call after a write lands.
 *
 * It remounts the page calling it, so close any dialog *before* calling — the
 * component doing the closing may not survive the render that follows.
 */
export const useCollectionReload = () => useContext(Context);
