// Pre-bundle theme init: applies the stored ACCORD_THEME before any
// stylesheet/bundle executes, so first paint never flashes the wrong
// scheme. Must stay in sync with ThemeProvider — the app default is
// "dark" (App.tsx defaultTheme), NOT the OS preference.
// External file (not inline) because the production CSP is script-src 'self'.
try {
	var stored = localStorage.getItem("ACCORD_THEME");
	var theme =
		stored === "dark" || stored === "light" || stored === "system"
			? stored
			: "dark";
	if (theme === "system") {
		theme = window.matchMedia("(prefers-color-scheme: dark)").matches
			? "dark"
			: "light";
	}
	document.documentElement.classList.add(theme);
	// Keep the hardcoded meta in sync with the resolved scheme —
	// dark bg ≈ #0a0a0a, light bg (oklch 0.985) ≈ #f3f5f5.
	var meta = document.querySelector('meta[name="theme-color"]');
	if (meta)
		meta.content = theme === "light" ? "#f3f5f5" : "#0a0a0a";
} catch {
	// Restricted storage / missing matchMedia — fall back to dark.
	document.documentElement.classList.add("dark");
}
