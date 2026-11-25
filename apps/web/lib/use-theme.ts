import { useSyncExternalStore } from "react";

import { currentTheme, subscribeTheme, type Theme } from "@/lib/theme";

/** The current theme, kept in step with `applyTheme`. Dark until the browser says otherwise. */
export function useTheme(): Theme {
  return useSyncExternalStore(subscribeTheme, currentTheme, () => "dark");
}
