import { fireEvent, screen } from "@testing-library/react";
import { vi } from "vitest";

import type { AuthUser } from "@/contexts/AuthContext";

type AuthState = {
	user: Partial<AuthUser> | null;
	isLoading?: boolean;
	logout?: () => void | Promise<void>;
	refetch?: () => void;
};

export function mockAuth(state: AuthState) {
	return {
		useAuth: () => ({
			user: state.user,
			isLoading: state.isLoading ?? false,
			logout: state.logout ?? vi.fn(),
			refetch: state.refetch ?? vi.fn(),
		}),
	};
}

type QueryOptions = { queryKey: readonly unknown[] };
type QueryResolver<T = unknown> = T | ((options: QueryOptions) => T);

type QueryMockOverrides = {
	queries?: Record<string, QueryResolver>;
	queryClient?: unknown;
	useMutation?: (config: unknown) => unknown;
};

const defaultQueryResult = {
	data: undefined,
	isLoading: false,
	error: null,
	refetch: vi.fn(),
};

export async function mockQuery(overrides: QueryMockOverrides = {}) {
	const actual =
		await vi.importActual<typeof import("@tanstack/react-query")>("@tanstack/react-query");

	return {
		...actual,
		...(overrides.queries
			? {
					useQuery: (options: QueryOptions) => {
						const key = String(options.queryKey[0]);
						const resolver = overrides.queries?.[key] ?? overrides.queries?.["*"];
						return typeof resolver === "function"
							? resolver(options)
							: (resolver ?? defaultQueryResult);
					},
				}
			: {}),
		...(overrides.queryClient
			? {
					useQueryClient: () => overrides.queryClient,
				}
			: {}),
		...(overrides.useMutation
			? {
					useMutation: overrides.useMutation,
				}
			: {}),
	};
}

export function mockToast() {
	return {
		toast: {
			success: vi.fn(),
			error: vi.fn(),
			info: vi.fn(),
			warning: vi.fn(),
		},
	};
}

// Base UI's Select trigger opens on pointerdown; jsdom needs both events
// to convince the underlying focus + open machinery.
export function openBaseUiSelect(trigger: HTMLElement) {
	fireEvent.pointerDown(trigger, { button: 0 });
	fireEvent.click(trigger);
}

// Base UI's onClick guards against committing unless pointerType is 'touch'
// OR the item is highlighted. Touch-typed pointer events satisfy the first
// branch — equivalent to a tap on mobile.
export function pickBaseUiOption(name: string | RegExp) {
	const option = screen.getByRole("option", { name });
	fireEvent.pointerEnter(option, { pointerType: "touch" });
	fireEvent.pointerDown(option, { pointerType: "touch", button: 0 });
	fireEvent.pointerUp(option, { pointerType: "touch", button: 0 });
	fireEvent.click(option);
}
