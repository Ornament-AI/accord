import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, AuthShellBoundary } from "@/contexts/AuthContext";
import type { PayComponentUpdate } from "@/lib/api/pay-setup";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { buildAuthMe, buildRoleAuthMe, ROLE_CAPABILITIES } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { openBaseUiSelect, pickBaseUiOption, pickDateByLabel } from "@/test/helpers";
import { server } from "@/test/msw-server";

import { CreatePayComponentDialog } from "./CreatePayComponentDialog";
import { CreateRateVersionDialog } from "./CreateRateVersionDialog";
import { EditPayComponentDialog } from "./EditPayComponentDialog";
import PayComponentDetailPage from "./PayComponentDetailPage";
import PayComponentsPage from "./PayComponentsPage";
import {
	buildPayComponent,
	buildRateVersion,
	createPayComponentHandlers,
} from "./pay-component-handlers";

const PAGE_TIMEOUT = 15_000;

function renderPayRoutes(initialEntry: string) {
	return render(
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<AuthShellBoundary>
						<MemoryRouter initialEntries={[initialEntry]}>
							<Routes>
								<Route path="/pay-components" element={<PayComponentsPage />} />
								<Route path="/pay-components/:componentId" element={<PayComponentDetailPage />} />
							</Routes>
						</MemoryRouter>
					</AuthShellBoundary>
				</AuthProvider>
			</ThemeProvider>
		</QueryClientProvider>,
	);
}

function renderDialog(ui: ReactElement) {
	return render(
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<MemoryRouter>{ui}</MemoryRouter>
				</AuthProvider>
			</ThemeProvider>
		</QueryClientProvider>,
	);
}

describe("Pay Components list page", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"renders pay components in the list table",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = createPayComponentHandlers();
			server.use(...authHandlers, ...payHandlers);

			renderPayRoutes("/pay-components");

			expect(
				await screen.findByTestId("pay-components-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(
				await screen.findByText("Basic Pay", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getByText("House Rent Allowance")).toBeInTheDocument();
			expect(screen.queryByRole("columnheader", { name: "Code" })).not.toBeInTheDocument();
			expect(screen.getAllByText("Earning").length).toBeGreaterThan(0);
		},
		PAGE_TIMEOUT,
	);

	it(
		"creates a pay component successfully",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = createPayComponentHandlers();
			server.use(...authHandlers, ...payHandlers);

			renderPayRoutes("/pay-components");

			expect(
				await screen.findByText("Basic Pay", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			fireEvent.click(screen.getByRole("button", { name: /^Add$/i }));

			expect(await screen.findByRole("heading", { name: "New Pay Component" })).toBeInTheDocument();
			fireEvent.change(screen.getByLabelText("Code"), { target: { value: "DA" } });
			fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Dearness Allowance" } });
			fireEvent.change(screen.getByLabelText("Display Order"), { target: { value: "3" } });
			fireEvent.click(screen.getByRole("button", { name: "Create component" }));

			await waitFor(() => {
				expect(
					screen.queryByRole("heading", { name: "New Pay Component" }),
				).not.toBeInTheDocument();
			});
			expect(await screen.findByText("Dearness Allowance")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it("surfaces 409 duplicate-code as a field error on code", async () => {
		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: payHandlers } = createPayComponentHandlers({
			createError: {
				status: 409,
				body: { detail: "Pay component code already exists", error: "ConflictError" },
			},
		});
		server.use(...authHandlers, ...payHandlers);

		renderDialog(<CreatePayComponentDialog open onOpenChange={vi.fn()} />);

		expect(await screen.findByRole("heading", { name: "New Pay Component" })).toBeInTheDocument();
		fireEvent.change(screen.getByLabelText("Code"), { target: { value: "BASIC" } });
		fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Dup" } });
		fireEvent.click(screen.getByRole("button", { name: "Create component" }));

		expect(await screen.findByText("Pay component code already exists")).toBeInTheDocument();
		expect(screen.getByLabelText("Code")).toHaveAttribute("aria-invalid", "true");
	});

	it(
		"gates Add pay component and row-edit on manage_master_data",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("payroll_reviewer"),
			});
			const { handlers: payHandlers } = createPayComponentHandlers();
			server.use(...authHandlers, ...payHandlers);

			renderPayRoutes("/pay-components");

			expect(
				await screen.findByText("Basic Pay", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /^Add$/i })).not.toBeInTheDocument();
			expect(screen.queryByRole("columnheader", { name: "Actions" })).not.toBeInTheDocument();
			fireEvent.click(screen.getByText("Basic Pay"));
			expect(screen.queryByRole("heading", { name: "Edit Pay Component" })).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"shows Add and opens edit on row click when manage_master_data is granted",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = createPayComponentHandlers();
			server.use(...authHandlers, ...payHandlers);

			renderPayRoutes("/pay-components");

			expect(
				await screen.findByText("Basic Pay", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getByRole("button", { name: /^Add$/i })).toBeInTheDocument();
			expect(screen.queryByRole("columnheader", { name: "Actions" })).not.toBeInTheDocument();
			fireEvent.click(screen.getByText("Basic Pay"));
			expect(
				await screen.findByRole("heading", { name: "Edit Pay Component" }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});

describe("Edit Pay Component dialog", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it("keeps code and classification read-only and patches only allowed fields", async () => {
		const patches: Array<{ componentId: string; body: PayComponentUpdate }> = [];
		const component = buildPayComponent({
			id: "pc-1",
			code: "BASIC",
			name: "Basic Pay",
			classification: "earning",
			display_order: 1,
			is_active: true,
		});
		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: payHandlers } = createPayComponentHandlers({
			components: [component],
			onPatch: (componentId, body) => {
				patches.push({ componentId, body });
			},
		});
		server.use(...authHandlers, ...payHandlers);

		renderDialog(<EditPayComponentDialog open onOpenChange={vi.fn()} component={component} />);

		expect(await screen.findByRole("heading", { name: "Edit Pay Component" })).toBeInTheDocument();

		const codeInput = screen.getByLabelText("Code");
		const classificationInput = screen.getByLabelText("Classification");
		expect(codeInput).toBeDisabled();
		expect(codeInput).toHaveAttribute("readonly");
		expect(classificationInput).toBeDisabled();
		expect(classificationInput).toHaveAttribute("readonly");

		fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Basic Pay Revised" } });
		fireEvent.change(screen.getByLabelText("Display Order"), { target: { value: "5" } });
		fireEvent.click(screen.getByRole("button", { name: "Save" }));

		await waitFor(() => {
			expect(patches).toHaveLength(1);
		});
		expect(patches[0]).toEqual({
			componentId: "pc-1",
			body: {
				name: "Basic Pay Revised",
				display_order: 5,
				is_active: true,
			},
		});
		expect(patches[0].body).not.toHaveProperty("code");
		expect(patches[0].body).not.toHaveProperty("classification");
	});
});

describe("Pay component detail page", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"renders rate version history and gates Add rate version",
		async () => {
			const withoutManage = buildAuthMe({
				active_organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
					role: "payroll_reviewer",
					capabilities: ROLE_CAPABILITIES.payroll_reviewer,
				},
			});
			const { handlers: authHandlers } = createAuthHandlers({ me: withoutManage });
			const { handlers: payHandlers } = createPayComponentHandlers({
				rateVersions: {
					"pc-1": [
						buildRateVersion({
							id: "rv-1",
							amount: "50000.00",
							calc_kind: "fixed_recurring_amount",
						}),
					],
				},
			});
			server.use(...authHandlers, ...payHandlers);

			renderPayRoutes("/pay-components/pc-1");

			const page = await screen.findByTestId(
				"pay-component-detail-page",
				{},
				{ timeout: PAGE_TIMEOUT },
			);
			expect(page).toBeInTheDocument();
			expect(within(page).getByRole("heading", { name: "BASIC" })).toBeInTheDocument();
			expect(within(page).getByText("Basic Pay")).toBeInTheDocument();
			expect(within(page).getByText("50000.00")).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /^Add$/i })).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"shows Add when manage_master_data is granted",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = createPayComponentHandlers();
			server.use(...authHandlers, ...payHandlers);

			renderPayRoutes("/pay-components/pc-1");

			expect(
				await screen.findByTestId("pay-component-detail-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getByRole("button", { name: /^Add$/i })).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});

describe("Create rate version dialog", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it("switches conditional fields by calc_kind and creates a version", async () => {
		const createdBodies: unknown[] = [];
		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: payHandlers } = createPayComponentHandlers({
			onCreateRateVersion: (_id, body) => {
				createdBodies.push(body);
			},
		});
		server.use(...authHandlers, ...payHandlers);

		const basisOptions = [
			buildPayComponent({ id: "pc-2", code: "HRA", name: "House Rent Allowance" }),
			buildPayComponent({ id: "pc-3", code: "BASIC", name: "Basic Pay" }),
		];

		renderDialog(
			<CreateRateVersionDialog
				open
				onOpenChange={vi.fn()}
				componentId="pc-1"
				basisOptions={basisOptions}
			/>,
		);

		expect(await screen.findByRole("heading", { name: "New Rate Version" })).toBeInTheDocument();
		expect(screen.getByLabelText("Calculation Kind")).toHaveTextContent("Fixed Recurring Amount");
		expect(screen.getByLabelText("Rounding Rule")).toHaveTextContent("Round half up (rupee)");

		// Default fixed_recurring_amount → amount visible, rate/basis hidden
		expect(screen.getByLabelText("Amount")).toBeInTheDocument();
		expect(screen.queryByLabelText("Rate")).not.toBeInTheDocument();
		expect(screen.queryByText("Basis Components")).not.toBeInTheDocument();

		openBaseUiSelect(screen.getByLabelText("Calculation Kind"));
		pickBaseUiOption("Percentage Of Component Bases");

		await waitFor(() => {
			expect(screen.queryByLabelText("Amount")).not.toBeInTheDocument();
			expect(screen.getByLabelText("Rate")).toBeInTheDocument();
			expect(screen.getByText("Basis Components")).toBeInTheDocument();
		});

		pickDateByLabel("Effective From", "2026-04-01");
		fireEvent.change(screen.getByLabelText("Rate"), { target: { value: "0.1000" } });

		const basisGroup = screen.getByRole("group", { name: "Basis Components" });
		fireEvent.click(within(basisGroup).getByRole("checkbox", { name: /BASIC/i }));

		fireEvent.click(screen.getByRole("button", { name: "Create rate version" }));

		await waitFor(() => {
			expect(createdBodies).toHaveLength(1);
		});
		expect(createdBodies[0]).toMatchObject({
			effective_from: "2026-04-01",
			calc_kind: "percentage_of_component_bases",
			rate: "0.1000",
			basis: ["BASIC"],
			rounding_rule: "ROUND_HALF_UP_RUPEE",
		});
		expect(createdBodies[0]).not.toHaveProperty("amount");
	});

	it("shows amount for accommodation_charge and rate for employer_employee_contribution", async () => {
		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: payHandlers } = createPayComponentHandlers();
		server.use(...authHandlers, ...payHandlers);

		renderDialog(
			<CreateRateVersionDialog
				open
				onOpenChange={vi.fn()}
				componentId="pc-1"
				basisOptions={[buildPayComponent({ id: "pc-2", code: "HRA", name: "HRA" })]}
			/>,
		);

		expect(await screen.findByRole("heading", { name: "New Rate Version" })).toBeInTheDocument();

		openBaseUiSelect(screen.getByLabelText("Calculation Kind"));
		pickBaseUiOption("Accommodation Charge");

		await waitFor(() => {
			expect(screen.getByLabelText("Amount")).toBeInTheDocument();
			expect(screen.queryByLabelText("Rate")).not.toBeInTheDocument();
		});

		openBaseUiSelect(screen.getByLabelText("Calculation Kind"));
		pickBaseUiOption("Employer Employee Contribution");

		await waitFor(() => {
			expect(screen.queryByLabelText("Amount")).not.toBeInTheDocument();
			expect(screen.getByLabelText("Rate")).toBeInTheDocument();
			expect(screen.getByText("Basis Components")).toBeInTheDocument();
		});
	});

	it("surfaces 409 overlap errors inline", async () => {
		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: payHandlers } = createPayComponentHandlers({
			rateVersionError: {
				status: 409,
				body: { detail: "Rate version periods overlap.", error: "ConflictError" },
			},
		});
		server.use(...authHandlers, ...payHandlers);

		renderDialog(
			<CreateRateVersionDialog open onOpenChange={vi.fn()} componentId="pc-1" basisOptions={[]} />,
		);

		expect(await screen.findByRole("heading", { name: "New Rate Version" })).toBeInTheDocument();
		pickDateByLabel("Effective From", "2026-01-01");
		fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "100.00" } });
		fireEvent.click(screen.getByRole("button", { name: "Create rate version" }));

		expect(await screen.findByRole("alert")).toHaveTextContent("Rate version periods overlap.");
	});
});

describe("Pay Components capability gate", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"denies direct URL access without view_master_data",
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

			renderPayRoutes("/pay-components");

			expect(
				await screen.findByText("You don't have access", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});
