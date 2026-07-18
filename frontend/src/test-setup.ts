import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll, vi } from "vitest";

import { server } from "@/test/msw-server";

beforeAll(() => {
	server.listen({ onUnhandledRequest: "bypass" });
});

afterEach(() => {
	server.resetHandlers();
});

afterAll(() => {
	server.close();
});

if (typeof window.localStorage?.getItem !== "function") {
	const store = new Map<string, string>();
	Object.defineProperty(window, "localStorage", {
		configurable: true,
		value: {
			clear: vi.fn(() => store.clear()),
			getItem: vi.fn((key: string) => store.get(key) ?? null),
			key: vi.fn((index: number) => Array.from(store.keys())[index] ?? null),
			removeItem: vi.fn((key: string) => store.delete(key)),
			setItem: vi.fn((key: string, value: string) => store.set(key, String(value))),
			get length() {
				return store.size;
			},
		},
	});
}

Object.defineProperty(window, "matchMedia", {
	writable: true,
	value: vi.fn().mockImplementation((query: string) => ({
		matches: false,
		media: query,
		onchange: null,
		addListener: vi.fn(),
		removeListener: vi.fn(),
		addEventListener: vi.fn(),
		removeEventListener: vi.fn(),
		dispatchEvent: vi.fn(),
	})),
});
