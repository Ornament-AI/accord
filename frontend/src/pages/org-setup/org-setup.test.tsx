import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { buildAuthMe, buildRoleAuthMe, ROLE_CAPABILITIES } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { mockToast, openBaseUiSelect, pickBaseUiOption } from "@/test/helpers";
import { server } from "@/test/msw-server";
import type { Capability } from "@/types/auth";

import { OrgSetupPage } from "./OrgSetupPage";
import { createOrgSetupHandlers } from "./org-setup-handlers";

vi.mock("sonner", () => mockToast());

const PAGE_TIMEOUT = 15_000;

function renderOrgSetupPage() {
	return render(
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<MemoryRouter>
						<OrgSetupPage />
					</MemoryRouter>
				</AuthProvider>
			</ThemeProvider>
		</QueryClientProvider>,
	);
}

async function setupPage(
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
	renderOrgSetupPage();
	expect(
		await screen.findByTestId("org-setup-page", {}, { timeout: PAGE_TIMEOUT }),
	).toBeInTheDocument();
}

describe("OrgSetupPage catalogs", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"renders each catalog tab list from MSW",
		async () => {
			await setupPage();

			expect(await screen.findByText("HO", {}, { timeout: PAGE_TIMEOUT })).toBeInTheDocument();
			expect(screen.getByText("Head Office")).toBeInTheDocument();

			fireEvent.click(screen.getByRole("tab", { name: "Payroll Units" }));
			expect(await screen.findByText("PU-HQ")).toBeInTheDocument();
			expect(screen.getByText("HQ Payroll")).toBeInTheDocument();

			fireEvent.click(screen.getByRole("tab", { name: "Posts" }));
			expect(await screen.findByText("Clerk")).toBeInTheDocument();
			expect(screen.getByText("Class III")).toBeInTheDocument();

			fireEvent.click(screen.getByRole("tab", { name: "Employee Groups" }));
			expect(await screen.findByText("GRP-A")).toBeInTheDocument();
			expect(screen.getByText("Group A")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"creates an office on the happy path",
		async () => {
			await setupPage("organization_administrator");

			fireEvent.click(screen.getByRole("button", { name: /Add office/i }));
			expect(await screen.findByRole("heading", { name: "Add office" })).toBeInTheDocument();

			fireEvent.change(screen.getByLabelText("Code"), { target: { value: "BR-01" } });
			fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Branch Office" } });
			openBaseUiSelect(screen.getByLabelText("Jurisdiction"));
			pickBaseUiOption("Worli");
			fireEvent.click(screen.getByRole("button", { name: "Create office" }));

			await waitFor(() => {
				expect(screen.queryByRole("heading", { name: "Add office" })).not.toBeInTheDocument();
			});
			expect(await screen.findByText("BR-01")).toBeInTheDocument();
			expect(screen.getByText("Branch Office")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"surfaces 409 create conflicts as a field error",
		async () => {
			await setupPage("organization_administrator", {
				createError: {
					status: 409,
					body: { detail: "Office code already exists", error: "ConflictError" },
				},
			});

			fireEvent.click(screen.getByRole("button", { name: /Add office/i }));
			expect(await screen.findByRole("heading", { name: "Add office" })).toBeInTheDocument();
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
			await setupPage();

			const codeCell = await screen.findByText("HO", {}, { timeout: PAGE_TIMEOUT });
			const row = codeCell.closest("tr");
			expect(row).not.toBeNull();
			fireEvent.click(row as HTMLElement);
			expect(await screen.findByRole("heading", { name: "Edit office" })).toBeInTheDocument();

			const codeInput = screen.getByLabelText("Code");
			expect(codeInput).toHaveValue("HO");
			expect(codeInput).toBeDisabled();
			expect(codeInput).toHaveAttribute("readonly");
		},
		PAGE_TIMEOUT,
	);
});

describe("OrgSetupPage settings", () => {
	beforeEach(() => {
		queryClient.clear();
		vi.clearAllMocks();
	});

	it(
		"updates settings on the happy path with a success toast",
		async () => {
			const { toast } = await import("sonner");
			await setupPage();

			fireEvent.click(screen.getByRole("tab", { name: "Settings" }));
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

	it(
		"surfaces 422 validation errors on settings fields",
		async () => {
			await setupPage("organization_administrator", {
				settingsUpdateError: {
					status: 422,
					body: {
						detail: [
							{
								loc: ["body", "locale"],
								msg: "Invalid locale",
								type: "value_error",
							},
						],
					},
				},
			});

			fireEvent.click(screen.getByRole("tab", { name: "Settings" }));
			expect(await screen.findByTestId("settings-tab")).toBeInTheDocument();
			fireEvent.change(screen.getByLabelText("Locale"), { target: { value: "nope" } });
			fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

			expect(await screen.findByText("Invalid locale")).toBeInTheDocument();
			const localeField = screen.getByLabelText("Locale").closest("div");
			expect(localeField).not.toBeNull();
			expect(within(localeField as HTMLElement).getByText("Invalid locale")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});

describe("OrgSetupPage capability gating", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"hides Add without manage_master_data and Settings without manage_organization",
		async () => {
			await setupPage("payroll_reviewer");

			expect(await screen.findByText("HO", {}, { timeout: PAGE_TIMEOUT })).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /Add office/i })).not.toBeInTheDocument();
			expect(screen.queryByRole("tab", { name: "Settings" })).not.toBeInTheDocument();
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
			renderOrgSetupPage();

			expect(
				await screen.findByText("You don't have access", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"shows Settings when manage_organization is granted",
		async () => {
			const caps = ROLE_CAPABILITIES.organization_administrator.filter(
				(cap): cap is Capability => cap === "view_master_data" || cap === "manage_organization",
			);
			const me = buildAuthMe({
				active_organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
					role: "organization_administrator",
					capabilities: caps,
				},
			});
			const { handlers: authHandlers } = createAuthHandlers({ me });
			const { handlers: orgHandlers } = createOrgSetupHandlers();
			server.use(...authHandlers, ...orgHandlers);
			renderOrgSetupPage();

			expect(
				await screen.findByTestId("org-setup-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getByRole("tab", { name: "Settings" })).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /Add office/i })).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});
