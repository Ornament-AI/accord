/**
 * Inline theme initialization to prevent flash of unstyled content.
 * Runs before React renders anything.
 */
try {
	const STORAGE_KEY = "ACCORD_THEME";
	const stored = localStorage.getItem(STORAGE_KEY);
	const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
	const theme = stored === "dark" || stored === "light" ? stored : prefersDark ? "dark" : "light";
	document.documentElement.classList.add(theme);
} catch {
	// SSR, restricted storage, or missing matchMedia — fall back to dark
	document.documentElement.classList.add("dark");
}
