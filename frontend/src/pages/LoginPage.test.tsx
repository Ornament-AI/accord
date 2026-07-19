import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import LoginPage from "@/pages/LoginPage";
import { createAuthHandlers } from "@/test/auth-handlers";
import { server } from "@/test/msw-server";

function renderLogin(path = "/login") {
	return render(
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<MemoryRouter initialEntries={[path]}>
						<Routes>
							<Route path="/login" element={<LoginPage />} />
						</Routes>
					</MemoryRouter>
				</AuthProvider>
			</ThemeProvider>
		</QueryClientProvider>,
	);
}

describe("LoginPage", () => {
	beforeEach(() => {
		queryClient.clear();
		sessionStorage.clear();
	});

	afterEach(() => {
		vi.restoreAllMocks();
		vi.unstubAllGlobals();
	});

	it("navigates to the auth login endpoint with return_to on Sign in", async () => {
		const assignSpy = vi.fn();
		vi.stubGlobal("location", {
			...window.location,
			assign: assignSpy,
			href: "http://localhost/login",
			pathname: "/login",
			search: "",
			hash: "",
		});

		const { handlers } = createAuthHandlers({ unauthenticated: true });
		server.use(...handlers);

		renderLogin("/login?returnTo=%2Fpay-runs");
		await screen.findByRole("button", { name: "Sign in" });

		fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

		await waitFor(() => {
			expect(assignSpy).toHaveBeenCalledWith("/api/auth/login?return_to=%2Fpay-runs");
		});
	});

	it("prefers the URL error param over sessionStorage auth_error", async () => {
		sessionStorage.setItem("auth_error", "Stored session message");
		const { handlers } = createAuthHandlers({ unauthenticated: true });
		server.use(...handlers);

		renderLogin("/login?error=auth_failed");

		expect(await screen.findByText("Sign-in failed. Please try again.")).toBeInTheDocument();
		expect(screen.queryByText("Stored session message")).not.toBeInTheDocument();
	});

	it("surfaces unknown error codes with a debug-friendly message", async () => {
		const { handlers } = createAuthHandlers({ unauthenticated: true });
		server.use(...handlers);

		renderLogin("/login?error=weird_code");

		expect(
			await screen.findByText("Unable to sign in (weird_code). Please try again."),
		).toBeInTheDocument();
	});
});
