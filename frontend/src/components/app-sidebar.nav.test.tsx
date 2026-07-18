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
import type { Capability, Role } from "@/types/auth";

function renderSidebar(initialPath = "/") {
	return render(
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<MemoryRouter initialEntries={[initialPath]}>
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
	const titles: string[] = [];
	for (const item of NAV_REGISTRY) {
		if (item.capability !== undefined && !capabilities.has(item.capability)) {
			continue;
		}
		titles.push(item.title);
		if (item.children) {
			for (const child of item.children) {
				if (child.capability === undefined || capabilities.has(child.capability as Capability)) {
					titles.push(child.title);
				}
			}
		}
	}
	return titles;
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

		renderSidebar("/organization/offices");

		await waitFor(() => {
			expect(screen.getByText("Dashboard")).toBeInTheDocument();
		});

		for (const title of expectedTitles) {
			expect(screen.getByText(title)).toBeInTheDocument();
		}

		const allTitles = NAV_REGISTRY.flatMap((item) => [
			item.title,
			...(item.children?.map((child) => child.title) ?? []),
		]);
		const hiddenTitles = allTitles.filter((title) => !expectedTitles.includes(title));
		for (const title of hiddenTitles) {
			expect(screen.queryByText(title)).not.toBeInTheDocument();
		}
	});

	it("nests Organization children in the sidebar", async () => {
		const { handlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		server.use(...handlers);

		renderSidebar("/organization/offices");

		await waitFor(() => {
			expect(screen.getByText("Organization")).toBeInTheDocument();
		});
		expect(screen.getByRole("link", { name: "Offices" })).toHaveAttribute(
			"href",
			"/organization/offices",
		);
		expect(screen.getByRole("link", { name: "Payroll Units" })).toHaveAttribute(
			"href",
			"/organization/payroll-units",
		);
		expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute(
			"href",
			"/organization/settings",
		);

		const folderTrigger = screen.getByRole("button", { name: /^Organization$/i });
		expect(folderTrigger).toHaveAttribute("data-active", "false");
		expect(screen.getByRole("link", { name: "Offices" })).toHaveAttribute("data-active", "true");
	});

	it("hides Settings for roles without manage_organization", async () => {
		const { handlers } = createAuthHandlers({ me: buildRoleAuthMe("payroll_reviewer") });
		server.use(...handlers);

		renderSidebar("/organization/offices");

		await waitFor(() => {
			expect(screen.getByText("Organization")).toBeInTheDocument();
		});
		expect(screen.getByRole("link", { name: "Offices" })).toBeInTheDocument();
		expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
	});
});
