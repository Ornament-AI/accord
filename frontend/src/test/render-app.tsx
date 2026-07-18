import { QueryClientProvider } from "@tanstack/react-query";
import { type RenderOptions, render } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";

import { AuthProvider, AuthShellBoundary } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { routes } from "@/router";

type RenderAppOptions = {
	initialEntries?: string[];
	renderOptions?: Omit<RenderOptions, "wrapper">;
};

function AppProviders({ children }: { children: ReactNode }) {
	return (
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<AuthShellBoundary>{children}</AuthShellBoundary>
				</AuthProvider>
			</ThemeProvider>
		</QueryClientProvider>
	);
}

export function renderApp({ initialEntries = ["/"], renderOptions }: RenderAppOptions = {}) {
	const router = createMemoryRouter(routes, { initialEntries });
	return {
		router,
		...render(<RouterProvider router={router} />, {
			...renderOptions,
			wrapper: AppProviders,
		}),
	};
}

export function renderWithAuthProviders(
	ui: ReactElement,
	renderOptions?: Omit<RenderOptions, "wrapper">,
) {
	return render(ui, {
		...renderOptions,
		wrapper: AppProviders,
	});
}
