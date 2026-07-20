import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function renderSidebar(initialPath = "/", { open = true }: { open?: boolean } = {}) {
	return render(
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<MemoryRouter initialEntries={[initialPath]}>
						<SidebarProvider open={open} onOpenChange={() => {}}>
							<AppSidebar />
						</SidebarProvider>
					</MemoryRouter>
				</AuthProvider>
			</ThemeProvider>
		</QueryClientProvider>,
	);
}

const RENDER_PATH = "/organization/offices";

function isPathActive(currentPath: string, itemPath: string) {
	if (itemPath === "/") {
		return currentPath === "/";
	}
	return currentPath === itemPath || currentPath.startsWith(`${itemPath}/`);
}

function expectedTitlesForRole(role: Role, pathname: string): string[] {
	const capabilities = new Set(ROLE_CAPABILITIES[role]);
	const titles: string[] = [];
	for (const item of NAV_REGISTRY) {
		if (item.capability !== undefined && !capabilities.has(item.capability)) {
			continue;
		}
		titles.push(item.title);
		if (item.children) {
			const visibleChildren = item.children.filter(
				(child) =>
					child.capability === undefined || capabilities.has(child.capability as Capability),
			);
			// A folder's children only mount when the folder is expanded, which the
			// sidebar does when one of its child routes is active for the current path.
			const sectionOpen = visibleChildren.some((child) => isPathActive(pathname, child.path));
			if (!sectionOpen) {
				continue;
			}
			for (const child of visibleChildren) {
				titles.push(child.title);
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
		"organization_administrator",
		"auditor",
	] as const)("shows the expected nav for %s", async (role) => {
		const expectedTitles = expectedTitlesForRole(role, RENDER_PATH);
		const { handlers } = createAuthHandlers({ me: buildRoleAuthMe(role) });
		server.use(...handlers);

		renderSidebar(RENDER_PATH);

		await waitFor(() => {
			expect(screen.getByText(expectedTitles[0])).toBeInTheDocument();
		});
		expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();

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
		expect(screen.getByRole("link", { name: "Employees" })).toHaveAttribute("href", "/employees");
		expect(screen.getByRole("link", { name: "Offices" })).toHaveAttribute(
			"href",
			"/organization/offices",
		);
		expect(screen.queryByRole("link", { name: "Payroll Units" })).not.toBeInTheDocument();
		expect(screen.getByRole("link", { name: "Posts" })).toHaveAttribute(
			"href",
			"/organization/posts",
		);
		expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();

		const folderTrigger = screen.getByRole("button", { name: /^Organization$/i });
		expect(folderTrigger).toHaveAttribute("data-active", "false");
		expect(screen.getByRole("link", { name: "Offices" })).toHaveAttribute("data-active", "true");
	});

	it("keeps Organization open on the Employees route", async () => {
		const { handlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		server.use(...handlers);

		renderSidebar("/employees");

		await waitFor(() => {
			expect(screen.getByRole("link", { name: "Employees" })).toBeInTheDocument();
		});
		expect(screen.getByRole("link", { name: "Employees" })).toHaveAttribute("data-active", "true");
	});

	it("exposes Organization children from a compact-sidebar flyout", async () => {
		const { handlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		server.use(...handlers);

		renderSidebar("/pay-runs", { open: false });

		await waitFor(() => {
			expect(screen.getByRole("button", { name: /^Organization$/i })).toBeInTheDocument();
		});

		expect(screen.queryByRole("menuitem", { name: "Employees" })).not.toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: /^Organization$/i }));

		await waitFor(() => {
			expect(screen.getByRole("menuitem", { name: "Employees" })).toBeInTheDocument();
		});
		expect(screen.getByRole("menuitem", { name: "Employees" })).toHaveAttribute(
			"href",
			"/employees",
		);
		expect(screen.getByRole("menuitem", { name: "Offices" })).toHaveAttribute(
			"href",
			"/organization/offices",
		);
		expect(screen.queryByRole("menuitem", { name: "Payroll Units" })).not.toBeInTheDocument();
		expect(screen.getByRole("menuitem", { name: "Posts" })).toHaveAttribute(
			"href",
			"/organization/posts",
		);
	});
});
