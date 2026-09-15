import { createContext, use, useCallback, useEffect, useMemo, useRef, useState } from "react";

export type Theme = "dark" | "light" | "system";

const STORAGE_KEY = "ACCORD_THEME";

function isValidTheme(value: unknown): value is Theme {
	return value === "dark" || value === "light" || value === "system";
}

type ThemeProviderProps = {
	children: React.ReactNode;
	defaultTheme?: Theme;
	storageKey?: string;
};

type ThemeProviderState = {
	theme: Theme;
	setTheme: (theme: Theme) => void;
};

const ThemeProviderContext = createContext<ThemeProviderState | null>(null);

function readInitialTheme(storageKey: string, defaultTheme: Theme): Theme {
	try {
		const stored = localStorage.getItem(storageKey);
		if (isValidTheme(stored)) {
			return stored;
		}
	} catch {
		// localStorage can be unavailable in private browsing contexts.
	}

	return defaultTheme;
}

/** Resolved-scheme colors — must stay in sync with the inline init in index.html. */
const THEME_COLORS = { dark: "#0a0a0a", light: "#f3f5f5" } as const;

function syncThemeColor(resolved: "dark" | "light") {
	document
		.querySelector('meta[name="theme-color"]')
		?.setAttribute("content", THEME_COLORS[resolved]);
}

export function ThemeProvider({
	children,
	defaultTheme = "system",
	storageKey = STORAGE_KEY,
}: ThemeProviderProps) {
	const [theme, setTheme] = useState<Theme>(() => readInitialTheme(storageKey, defaultTheme));

	useEffect(() => {
		const root = window.document.documentElement;
		root.classList.remove("light", "dark");

		const mediaQuery =
			typeof window.matchMedia === "function"
				? window.matchMedia("(prefers-color-scheme: dark)")
				: null;
		const applyTheme = () => {
			const resolved = theme === "system" ? (mediaQuery?.matches ? "dark" : "light") : theme;
			root.classList.add(resolved);
			syncThemeColor(resolved);
		};

		applyTheme();

		const handleChange = () => {
			if (theme !== "system") {
				return;
			}

			root.classList.remove("light", "dark");
			const resolved = mediaQuery?.matches ? "dark" : "light";
			root.classList.add(resolved);
			syncThemeColor(resolved);
		};

		if (!mediaQuery) {
			return;
		}

		if (mediaQuery.addEventListener) {
			mediaQuery.addEventListener("change", handleChange);
		} else {
			mediaQuery.addListener(handleChange);
		}

		return () => {
			if (mediaQuery.removeEventListener) {
				mediaQuery.removeEventListener("change", handleChange);
			} else {
				mediaQuery.removeListener(handleChange);
			}
		};
	}, [theme]);

	const storageKeyRef = useRef(storageKey);
	storageKeyRef.current = storageKey;

	const setThemeWithStorage = useCallback((nextTheme: Theme) => {
		try {
			localStorage.setItem(storageKeyRef.current, nextTheme);
		} catch {
			// localStorage can be unavailable in private browsing contexts.
		}

		setTheme(nextTheme);
	}, []);

	const value = useMemo(
		() => ({
			theme,
			setTheme: setThemeWithStorage,
		}),
		[theme, setThemeWithStorage],
	);

	return <ThemeProviderContext value={value}>{children}</ThemeProviderContext>;
}

export function useTheme() {
	const context = use(ThemeProviderContext);
	if (context === null) {
		throw new Error("useTheme must be used within a ThemeProvider");
	}

	return context;
}
