import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreateOrganizationDialog } from "@/components/create-organization-dialog";
import { AuthProvider } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import { buildNoOrgAuthMe } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { server } from "@/test/msw-server";

function renderDialog(open = true) {
	const onOpenChange = vi.fn();
	render(
		<QueryClientProvider client={queryClient}>
			<AuthProvider>
				<CreateOrganizationDialog open={open} onOpenChange={onOpenChange} />
			</AuthProvider>
		</QueryClientProvider>,
	);
	return { onOpenChange };
}

describe("CreateOrganizationDialog", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("blocks empty name on the client", async () => {
		const { handlers } = createAuthHandlers({ me: buildNoOrgAuthMe() });
		server.use(...handlers);

		renderDialog();
		await screen.findByRole("heading", { name: "Create organization" });

		fireEvent.click(screen.getByRole("button", { name: "Create organization" }));

		expect(await screen.findByText("Name is required.")).toBeInTheDocument();
		expect(screen.queryByLabelText("Slug")).not.toBeInTheDocument();
	});

	it("creates an organization with an auto-generated slug and closes the dialog", async () => {
		const createBodies: Array<{ name: string; slug: string }> = [];
		const { handlers } = createAuthHandlers({
			me: buildNoOrgAuthMe(),
			onCreateOrganization: (body) => {
				createBodies.push(body);
				return undefined;
			},
		});
		server.use(...handlers);

		const { onOpenChange } = renderDialog();
		await screen.findByLabelText("Name");

		fireEvent.change(screen.getByLabelText("Name"), {
			target: { value: "North Star" },
		});
		fireEvent.click(screen.getByRole("button", { name: "Create organization" }));

		await waitFor(() => {
			expect(onOpenChange).toHaveBeenCalledWith(false);
		});
		expect(createBodies).toEqual([{ name: "North Star", slug: "north-star" }]);
	});

	it("retries with a disambiguated slug on 409 without exposing slug UI", async () => {
		let attempts = 0;
		const createBodies: Array<{ name: string; slug: string }> = [];
		const { handlers } = createAuthHandlers({
			me: buildNoOrgAuthMe(),
			onCreateOrganization: (body) => {
				attempts += 1;
				createBodies.push(body);
				if (attempts === 1) {
					return {
						status: 409,
						body: { detail: "Organization slug already taken" },
					};
				}
				return undefined;
			},
		});
		server.use(...handlers);

		const { onOpenChange } = renderDialog();
		await screen.findByLabelText("Name");

		fireEvent.change(screen.getByLabelText("Name"), {
			target: { value: "Taken Org" },
		});
		fireEvent.click(screen.getByRole("button", { name: "Create organization" }));

		await waitFor(() => {
			expect(onOpenChange).toHaveBeenCalledWith(false);
		});
		expect(screen.queryByText("This slug is already taken")).not.toBeInTheDocument();
		expect(screen.queryByLabelText("Slug")).not.toBeInTheDocument();
		expect(createBodies).toHaveLength(2);
		expect(createBodies[0]).toEqual({ name: "Taken Org", slug: "taken-org" });
		expect(createBodies[1]?.slug).toMatch(/^taken-org-[a-z0-9]{6}$/);
	});
});
