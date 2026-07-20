import { render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { buildAuthMe, buildNoOrgAuthMe, buildUnprovisionedAuthMe } from "@/test/auth-fixtures";

function Probe() {
	const { user, accessState, organization, membership, hasCapability, isLoading } = useAuth();
	if (isLoading) return <div data-testid="loading">loading</div>;
	return (
		<div>
			<span data-testid="email">{user?.email ?? "none"}</span>
			<span data-testid="access">{accessState ?? "none"}</span>
			<span data-testid="org">{organization?.name ?? "none"}</span>
			<span data-testid="role">{membership?.role ?? "none"}</span>
			<span data-testid="has-manage">{String(hasCapability("manage_organization"))}</span>
		</div>
	);
}

describe("AuthContext", () => {
	const server = setupServer();

	beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
	afterEach(() => server.resetHandlers());
	afterAll(() => server.close());

	it("loads singular active me payload", async () => {
		server.use(http.get("/api/auth/me", () => HttpResponse.json(buildAuthMe())));
		render(
			<AuthProvider>
				<Probe />
			</AuthProvider>,
		);
		await waitFor(() => expect(screen.getByTestId("email")).toHaveTextContent("ada@example.com"));
		expect(screen.getByTestId("access")).toHaveTextContent("active");
		expect(screen.getByTestId("org")).toHaveTextContent("Acme Payroll");
		expect(screen.getByTestId("role")).toHaveTextContent("organization_administrator");
		expect(screen.getByTestId("has-manage")).toHaveTextContent("true");
	});

	it("surfaces unbootstrapped state", async () => {
		server.use(http.get("/api/auth/me", () => HttpResponse.json(buildNoOrgAuthMe())));
		render(
			<AuthProvider>
				<Probe />
			</AuthProvider>,
		);
		await waitFor(() => expect(screen.getByTestId("access")).toHaveTextContent("unbootstrapped"));
		expect(screen.getByTestId("org")).toHaveTextContent("none");
		expect(screen.getByTestId("role")).toHaveTextContent("none");
	});

	it("surfaces unprovisioned state with organization", async () => {
		server.use(http.get("/api/auth/me", () => HttpResponse.json(buildUnprovisionedAuthMe())));
		render(
			<AuthProvider>
				<Probe />
			</AuthProvider>,
		);
		await waitFor(() => expect(screen.getByTestId("access")).toHaveTextContent("unprovisioned"));
		expect(screen.getByTestId("org")).toHaveTextContent("Acme Payroll");
		expect(screen.getByTestId("role")).toHaveTextContent("none");
	});
});
