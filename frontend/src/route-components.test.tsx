import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { AuthProvider } from "@/contexts/AuthContext";
import { ProtectedLayout } from "@/route-components";
import {
	buildAuthMe,
	buildNoOrgAuthMe,
	buildUnprovisionedAuthMe,
} from "@/test/auth-fixtures";

vi.mock("@/components/protected-shell", () => ({
	ProtectedShell: () => <div data-testid="protected-shell">shell</div>,
}));

describe("ProtectedLayout", () => {
	const server = setupServer();

	beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
	afterEach(() => server.resetHandlers());
	afterAll(() => server.close());

	function renderLayout() {
		return render(
			<AuthProvider>
				<MemoryRouter initialEntries={["/"]}>
					<Routes>
						<Route path="/" element={<ProtectedLayout />} />
						<Route path="/login" element={<div>login</div>} />
					</Routes>
				</MemoryRouter>
			</AuthProvider>,
		);
	}

	it("shows deployment not ready when unbootstrapped", async () => {
		server.use(http.get("/api/auth/me", () => HttpResponse.json(buildNoOrgAuthMe())));
		renderLayout();
		await waitFor(() =>
			expect(screen.getByTestId("deployment-not-ready-page")).toBeInTheDocument(),
		);
	});

	it("shows not provisioned when org exists without membership", async () => {
		server.use(http.get("/api/auth/me", () => HttpResponse.json(buildUnprovisionedAuthMe())));
		renderLayout();
		await waitFor(() => expect(screen.getByTestId("not-provisioned-page")).toBeInTheDocument());
	});

	it("renders shell when active", async () => {
		server.use(http.get("/api/auth/me", () => HttpResponse.json(buildAuthMe())));
		renderLayout();
		await waitFor(() => expect(screen.getByTestId("protected-shell")).toBeInTheDocument());
	});
});
