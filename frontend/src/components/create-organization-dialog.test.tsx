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

	it("blocks empty name/slug on the client", async () => {
		const { handlers } = createAuthHandlers({ me: buildNoOrgAuthMe() });
		server.use(...handlers);

		renderDialog();
		await screen.findByRole("heading", { name: "Create organization" });

		fireEvent.click(screen.getByRole("button", { name: "Create organization" }));

		expect(await screen.findByText("Name and slug are required.")).toBeInTheDocument();
	});

	it("auto-suggests a slug from the organization name until the slug is edited", async () => {
		const { handlers } = createAuthHandlers({ me: buildNoOrgAuthMe() });
		server.use(...handlers);

		renderDialog();
		await screen.findByLabelText("Name");

		fireEvent.change(screen.getByLabelText("Name"), {
			target: { value: "North Star Payroll" },
		});
		expect(screen.getByLabelText("Slug")).toHaveValue("north-star-payroll");

		fireEvent.change(screen.getByLabelText("Slug"), {
			target: { value: "custom-slug" },
		});
		fireEvent.change(screen.getByLabelText("Name"), {
			target: { value: "Different Name" },
		});
		expect(screen.getByLabelText("Slug")).toHaveValue("custom-slug");
	});

	it("creates an organization successfully and closes the dialog", async () => {
		const { handlers } = createAuthHandlers({ me: buildNoOrgAuthMe() });
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
	});

	it("shows a field-level slug error on 409 without closing", async () => {
		const { handlers } = createAuthHandlers({
			me: buildNoOrgAuthMe(),
			onCreateOrganization: () => ({
				status: 409,
				body: { detail: "Organization slug already taken" },
			}),
		});
		server.use(...handlers);

		const { onOpenChange } = renderDialog();
		await screen.findByLabelText("Name");

		fireEvent.change(screen.getByLabelText("Name"), {
			target: { value: "Taken Org" },
		});
		fireEvent.click(screen.getByRole("button", { name: "Create organization" }));

		expect(await screen.findByText("This slug is already taken")).toBeInTheDocument();
		expect(onOpenChange).not.toHaveBeenCalledWith(false);
		expect(screen.getByRole("heading", { name: "Create organization" })).toBeInTheDocument();
	});
});
