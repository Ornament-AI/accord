import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import {
	buildAuthMe,
	buildNoOrgAuthMe,
	buildRoleAuthMe,
	ROLE_CAPABILITIES,
} from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { server } from "@/test/msw-server";
import { renderApp, renderWithAuthProviders } from "@/test/render-app";

describe("AuthContext and protected shell", () => {
	beforeEach(() => {
		queryClient.clear();
		sessionStorage.clear();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("redirects unauthenticated users from the app shell to login", async () => {
		const { handlers } = createAuthHandlers({ unauthenticated: true });
		server.use(...handlers);

		const { router } = renderApp({ initialEntries: ["/"] });

		await waitFor(() => {
			expect(router.state.location.pathname).toBe("/login");
		});
		expect(router.state.location.search).toContain("returnTo");
	});

	it("shows the no-organization empty state when memberships are empty", async () => {
		const { handlers } = createAuthHandlers({ me: buildNoOrgAuthMe() });
		server.use(...handlers);

		renderApp({ initialEntries: ["/"] });

		expect(await screen.findByText("Create your first organization")).toBeInTheDocument();
		expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
	});

	it("loads an authenticated org session and evaluates hasCapability strictly", async () => {
		const { handlers } = createAuthHandlers({ me: buildRoleAuthMe("auditor") });
		server.use(...handlers);

		function DualCapabilityProbe() {
			const { hasCapability, user, activeOrganization, isLoading } = useAuth();
			if (isLoading) return <div>loading</div>;
			return (
				<div>
					<span data-testid="user-email">{user?.email ?? "none"}</span>
					<span data-testid="active-org">{activeOrganization?.name ?? "none"}</span>
					<span data-testid="has-audit">{String(hasCapability("view_audit"))}</span>
					<span data-testid="has-manage">{String(hasCapability("manage_organization"))}</span>
				</div>
			);
		}

		renderWithAuthProviders(<DualCapabilityProbe />);

		await waitFor(() => {
			expect(screen.getByTestId("user-email")).toHaveTextContent("ada@example.com");
		});
		expect(screen.getByTestId("active-org")).toHaveTextContent("Acme Payroll");
		expect(screen.getByTestId("has-audit")).toHaveTextContent("true");
		expect(screen.getByTestId("has-manage")).toHaveTextContent("false");
		expect(ROLE_CAPABILITIES.auditor).toContain("view_audit");
		expect(ROLE_CAPABILITIES.auditor).not.toContain("manage_organization");
	});

	it("does not grant capabilities from is_platform_admin alone", async () => {
		const { handlers } = createAuthHandlers({
			me: buildAuthMe({
				is_platform_admin: true,
				active_organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
					role: "auditor",
					capabilities: ["view_audit"],
				},
			}),
		});
		server.use(...handlers);

		function PlatformAdminProbe() {
			const { hasCapability, isLoading } = useAuth();
			if (isLoading) return <div>loading</div>;
			return <span data-testid="has-cap">{String(hasCapability("manage_organization"))}</span>;
		}

		renderWithAuthProviders(<PlatformAdminProbe />);

		await waitFor(() => {
			expect(screen.getByTestId("has-cap")).toHaveTextContent("false");
		});
	});

	it("returns a conflict response through createOrganization without swallowing it", async () => {
		const { handlers } = createAuthHandlers({
			me: buildNoOrgAuthMe(),
			onCreateOrganization: () => ({
				status: 409,
				body: { detail: "Organization slug already taken" },
			}),
		});
		server.use(...handlers);

		function CreateProbe() {
			const { createOrganization, isLoading } = useAuth();
			if (isLoading) return <div>loading</div>;
			return (
				<button
					type="button"
					onClick={() => {
						void createOrganization({ name: "Dup", slug: "dup" }).catch((error: unknown) => {
							const message = error instanceof Error ? error.message : "unknown";
							document.body.setAttribute("data-create-error", message);
						});
					}}
				>
					create
				</button>
			);
		}

		renderWithAuthProviders(<CreateProbe />);
		await screen.findByRole("button", { name: "create" });
		screen.getByRole("button", { name: "create" }).click();

		await waitFor(() => {
			expect(document.body.getAttribute("data-create-error")).toMatch(
				/already taken|409|Conflict/i,
			);
		});
	});
});
