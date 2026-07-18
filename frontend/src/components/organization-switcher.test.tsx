import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OrganizationSwitcher } from "@/components/organization-switcher";
import { SidebarProvider } from "@/components/ui/sidebar";
import { AuthProvider, AuthShellBoundary } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { buildAuthMe, ROLE_CAPABILITIES } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { server } from "@/test/msw-server";

describe("OrganizationSwitcher", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("lists memberships, switches org, clears the query cache, and reflects the new active org", async () => {
		const switchSpy = vi.fn();
		const clearSpy = vi.spyOn(queryClient, "clear");

		const { handlers } = createAuthHandlers({
			me: buildAuthMe(),
			onSwitchOrganization: (organizationId) => {
				switchSpy(organizationId);
				return {
					...buildAuthMe(),
					active_organization: {
						id: "org-beta",
						name: "Beta Co",
						slug: "beta-co",
						role: "auditor",
						capabilities: ROLE_CAPABILITIES.auditor,
					},
				};
			},
		});
		server.use(...handlers);

		render(
			<QueryClientProvider client={queryClient}>
				<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
					<AuthProvider>
						<AuthShellBoundary>
							<SidebarProvider>
								<OrganizationSwitcher />
								<div data-testid="shell-marker">shell</div>
							</SidebarProvider>
						</AuthShellBoundary>
					</AuthProvider>
				</ThemeProvider>
			</QueryClientProvider>,
		);

		const trigger = await screen.findByRole("button", { name: /Acme Payroll/i });
		fireEvent.click(trigger);

		const menu = await screen.findByRole("menu");
		expect(within(menu).getByText("Acme Payroll")).toBeInTheDocument();
		expect(within(menu).getByText("Beta Co")).toBeInTheDocument();

		fireEvent.click(within(menu).getByText("Beta Co"));

		await waitFor(() => {
			expect(switchSpy).toHaveBeenCalledWith("org-beta");
		});
		await waitFor(() => {
			expect(clearSpy).toHaveBeenCalled();
		});
		expect(await screen.findByRole("button", { name: /Beta Co/i })).toBeInTheDocument();
	});
});
