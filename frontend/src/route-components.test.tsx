import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { queryClient } from "@/lib/query-client";
import { buildAuthMe, buildRoleAuthMe } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { server } from "@/test/msw-server";
import { renderApp } from "@/test/render-app";

describe("authenticated routing", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it("asks a multi-membership session to select an organization", async () => {
		const organizations = [
			{
				id: "org-acme",
				name: "Acme Payroll",
				slug: "acme-payroll",
				role: "organization_administrator" as const,
			},
			{
				id: "org-beta",
				name: "Beta Payroll",
				slug: "beta-payroll",
				role: "auditor" as const,
			},
		];
		let switchedTo: string | null = null;
		const { handlers } = createAuthHandlers({
			me: buildAuthMe({ active_organization: null, organizations }),
			onSwitchOrganization: (organizationId) => {
				switchedTo = organizationId;
				return buildRoleAuthMe("auditor", organizationId);
			},
		});
		server.use(...handlers);

		renderApp();

		expect(await screen.findByRole("heading", { name: "Select an organization" })).toBeVisible();
		fireEvent.click(screen.getByRole("button", { name: /Beta Payroll.*beta-payroll/ }));

		await waitFor(() => {
			expect(switchedTo).toBe("org-beta");
			expect(screen.queryByTestId("organization-selection-page")).not.toBeInTheDocument();
		});
	});
});
