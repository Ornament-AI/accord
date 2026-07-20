import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { queryClient } from "@/lib/query-client";
import { createOrgSetupHandlers } from "@/pages/org-setup/org-setup-handlers";
import { buildRoleAuthMe } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { server } from "@/test/msw-server";
import { renderApp } from "@/test/render-app";

describe("capability-gated direct URL access", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it("shows an access-denied empty state when the user lacks the capability", async () => {
		const { handlers } = createAuthHandlers({ me: buildRoleAuthMe("auditor") });
		server.use(...handlers);

		renderApp({ initialEntries: ["/organization/offices"] });

		expect(await screen.findByText("You Don't Have Access")).toBeInTheDocument();
	});

	it("renders the organization offices page when the user has the capability", async () => {
		const { handlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: orgSetupHandlers } = createOrgSetupHandlers();
		server.use(...handlers, ...orgSetupHandlers);

		renderApp({ initialEntries: ["/organization"] });

		await waitFor(async () => {
			expect(await screen.findByTestId("offices-page")).toBeInTheDocument();
		});
	});
});
