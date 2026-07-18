import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryClient } from "@/lib/query-client";
import { buildAuthMe, buildRoleAuthMe, ROLE_CAPABILITIES } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { mockToast, openBaseUiSelect, pickBaseUiOption } from "@/test/helpers";
import { server } from "@/test/msw-server";
import { renderApp } from "@/test/render-app";

import { createOrgSetupHandlers } from "./org-setup-handlers";

vi.mock("sonner", () => mockToast());

const PAGE_TIMEOUT = 15_000;

async function setupPage(
	path: string,
	role:
		| "organization_administrator"
		| "payroll_reviewer"
		| "payroll_preparer" = "organization_administrator",
	handlerOptions: Parameters<typeof createOrgSetupHandlers>[0] = {},
) {
	const { handlers: authHandlers } = createAuthHandlers({
		me: buildRoleAuthMe(role),
	});
	const { handlers: orgHandlers } = createOrgSetupHandlers(handlerOptions);
	server.use(...authHandlers, ...orgHandlers);
	renderApp({ initialEntries: [path] });
}

describe("Org setup catalog pages", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"renders each catalog page list from MSW",
		async () => {
			await setupPage("/organization/offices");
			expect(
				await screen.findByTestId("offices-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(await screen.findByText("HO", {}, { timeout: PAGE_TIMEOUT })).toBeInTheDocument();
			expect(screen.getByText("Head Office")).toBeInTheDocument();

			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: orgHandlers } = createOrgSetupHandlers();
			server.use(...authHandlers, ...orgHandlers);

			renderApp({ initialEntries: ["/organization/payroll-units"] });
			expect(
				await screen.findByTestId("payroll-units-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(await screen.findByText("PU-HQ")).toBeInTheDocument();
			expect(screen.getByText("HQ Payroll")).toBeInTheDocument();

			renderApp({ initialEntries: ["/organization/posts"] });
			expect(
				await screen.findByTestId("posts-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(await screen.findByText("Clerk")).toBeInTheDocument();
			expect(screen.getByText("Class III")).toBeInTheDocument();

			renderApp({ initialEntries: ["/organization/employee-groups"] });
			expect(
				await screen.findByTestId("employee-groups-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(await screen.findByText("GRP-A")).toBeInTheDocument();
			expect(screen.getByText("Group A")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"creates an office on the happy path",
		async () => {
			await setupPage("/organization/offices", "organization_administrator");
			expect(
				await screen.findByTestId("offices-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();

			fireEvent.click(screen.getByRole("button", { name: /^Add$/i }));
			expect(await screen.findByRole("heading", { name: "Add Office" })).toBeInTheDocument();

			fireEvent.change(screen.getByLabelText("Code"), { target: { value: "BR-01" } });
			fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Branch Office" } });
			openBaseUiSelect(screen.getByLabelText("Jurisdiction"));
			pickBaseUiOption("Worli");
			fireEvent.click(screen.getByRole("button", { name: "Create office" }));

			await waitFor(() => {
				expect(screen.queryByRole("heading", { name: "Add Office" })).not.toBeInTheDocument();
			});
			expect(await screen.findByText("BR-01")).toBeInTheDocument();
			expect(screen.getByText("Branch Office")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"surfaces 409 create conflicts as a field error",
		async () => {
			await setupPage("/organization/offices", "organization_administrator", {
				createError: {
					status: 409,
					body: { detail: "Office code already exists", error: "ConflictError" },
				},
			});
			expect(
				await screen.findByTestId("offices-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();

			fireEvent.click(screen.getByRole("button", { name: /^Add$/i }));
			expect(await screen.findByRole("heading", { name: "Add Office" })).toBeInTheDocument();
			fireEvent.change(screen.getByLabelText("Code"), { target: { value: "DUP" } });
			fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Duplicate" } });
			fireEvent.click(screen.getByRole("button", { name: "Create office" }));

			expect(await screen.findByText("This code is already in use")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"keeps the natural-key field immutable in the edit dialog",
		async () => {
			await setupPage("/organization/offices");
			expect(
				await screen.findByTestId("offices-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();

			const codeCell = await screen.findByText("HO", {}, { timeout: PAGE_TIMEOUT });
			const row = codeCell.closest("tr");
			expect(row).not.toBeNull();
			fireEvent.click(row as HTMLElement);
			expect(await screen.findByRole("heading", { name: "Edit Office" })).toBeInTheDocument();

			const codeInput = screen.getByLabelText("Code");
			expect(codeInput).toHaveValue("HO");
			expect(codeInput).toBeDisabled();
			expect(codeInput).toHaveAttribute("readonly");
		},
		PAGE_TIMEOUT,
	);
});

describe("Org setup capability gating", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"hides Add without manage_master_data",
		async () => {
			await setupPage("/organization/offices", "payroll_reviewer");

			expect(await screen.findByText("HO", {}, { timeout: PAGE_TIMEOUT })).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /^Add$/i })).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"denies direct access without view_master_data",
		async () => {
			const me = buildAuthMe({
				active_organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
					role: "report_releaser",
					capabilities: ROLE_CAPABILITIES.report_releaser,
				},
			});
			const { handlers } = createAuthHandlers({ me });
			server.use(...handlers);
			renderApp({ initialEntries: ["/organization/offices"] });

			expect(
				await screen.findByText("You don't have access", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"redirects /organization to offices",
		async () => {
			await setupPage("/organization");
			expect(
				await screen.findByTestId("offices-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});

describe("Org settings page", () => {
	beforeEach(() => {
		queryClient.clear();
		vi.clearAllMocks();
	});

	it(
		"updates settings on the happy path with a success toast",
		async () => {
			const { toast } = await import("sonner");
			await setupPage("/organization/settings");
			expect(
				await screen.findByTestId("settings-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(await screen.findByTestId("settings-tab")).toBeInTheDocument();
			expect(screen.getByLabelText("Locale")).toHaveValue("en-IN");

			fireEvent.change(screen.getByLabelText("Locale"), { target: { value: "en-GB" } });
			fireEvent.change(screen.getByLabelText("Currency"), { target: { value: "GBP" } });
			fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

			await waitFor(() => {
				expect(toast.success).toHaveBeenCalledWith("Organization settings saved");
			});
		},
		PAGE_TIMEOUT,
	);
});
