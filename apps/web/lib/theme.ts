export type Theme = "dark" | "light";

export const THEME_KEY = "devpilot-theme";

/** Runs in <head> before paint: dark is the default, `light` adds a class on <html>. */
export const THEME_INIT_SCRIPT = `try{if(localStorage.getItem("${THEME_KEY}")==="light"){document.documentElement.classList.add("light")}}catch(e){}`;

export function readTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

const listeners = new Set<() => void>();

export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The theme the page is showing right now. The class on <html> is the source of truth. */
export function currentTheme(): Theme {
  return document.documentElement.classList.contains("light") ? "light" : "dark";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("light", theme === "light");
  listeners.forEach((l) => l());
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* storage can be blocked: the theme still applies for this visit */
  }
}
