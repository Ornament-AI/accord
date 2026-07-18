import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppSidebar } from "@/components/app-sidebar";
import { SidebarProvider } from "@/components/ui/sidebar";
import { AuthProvider } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { buildAuthMe } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { server } from "@/test/msw-server";

describe("logout flow", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	afterEach(() => {
		vi.restoreAllMocks();
		vi.unstubAllGlobals();
	});

	it("calls POST /api/auth/logout and navigates to /login", async () => {
		const logoutSpy = vi.fn();
		const assignSpy = vi.fn();
		vi.stubGlobal("location", {
			...window.location,
			assign: assignSpy,
			href: "http://localhost/",
			pathname: "/",
			search: "",
			hash: "",
		});

		const { handlers } = createAuthHandlers({
			me: buildAuthMe(),
			onLogout: logoutSpy,
		});
		server.use(...handlers);

		render(
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

		const accountTrigger = await screen.findByRole("button", { name: /Ada Lovelace/i });
		fireEvent.click(accountTrigger);

		const signOut = await screen.findByText("Sign out");
		fireEvent.click(signOut);

		await waitFor(() => {
			expect(logoutSpy).toHaveBeenCalled();
		});
		await waitFor(() => {
			expect(assignSpy).toHaveBeenCalledWith("/login");
		});
	});
});
