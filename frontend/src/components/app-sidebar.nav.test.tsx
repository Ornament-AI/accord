import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";

import { AppSidebar } from "@/components/app-sidebar";
import { SidebarProvider } from "@/components/ui/sidebar";
import { AuthProvider } from "@/contexts/AuthContext";
import { NAV_REGISTRY } from "@/lib/nav-registry";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { buildRoleAuthMe, ROLE_CAPABILITIES } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { server } from "@/test/msw-server";
import type { Role } from "@/types/auth";

function renderSidebar() {
	return render(
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<MemoryRouter>
						<SidebarProvider>
							<AppSidebar />
						</SidebarProvider>
					</MemoryRouter>
				</AuthProvider>
			</ThemeProvider>
		</QueryClientProvider>,
	);
}

function expectedTitlesForRole(role: Role): string[] {
	const capabilities = new Set(ROLE_CAPABILITIES[role]);
	return NAV_REGISTRY.filter(
		(item) => item.capability === undefined || capabilities.has(item.capability),
	).map((item) => item.title);
}

describe("capability-aware sidebar nav", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it.each([
		["organization_administrator", expectedTitlesForRole("organization_administrator")],
		["auditor", expectedTitlesForRole("auditor")],
	] as const)("shows the expected nav for %s", async (role, expectedTitles) => {
		const { handlers } = createAuthHandlers({ me: buildRoleAuthMe(role) });
		server.use(...handlers);

		renderSidebar();

		await waitFor(() => {
			expect(screen.getByText("Dashboard")).toBeInTheDocument();
		});

		for (const title of expectedTitles) {
			expect(screen.getByText(title)).toBeInTheDocument();
		}

		const hiddenTitles = NAV_REGISTRY.map((item) => item.title).filter(
			(title) => !expectedTitles.includes(title),
		);
		for (const title of hiddenTitles) {
			expect(screen.queryByText(title)).not.toBeInTheDocument();
		}
	});
});
