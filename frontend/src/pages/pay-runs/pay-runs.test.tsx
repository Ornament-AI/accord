import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, AuthShellBoundary } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { buildEmployeeDetail, createEmployeeHandlers } from "@/pages/employees/employee-handlers";
import { buildAuthMe, buildRoleAuthMe, ROLE_CAPABILITIES } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { mockToast, openBaseUiSelect, pickBaseUiOption } from "@/test/helpers";
import { server } from "@/test/msw-server";

import { CreatePeriodDialog } from "./CreatePeriodDialog";
import PayRunDetailPage from "./PayRunDetailPage";
import PayRunsPage from "./PayRunsPage";
import {
	buildCurrentVersion,
	buildPeriod,
	buildRun,
	buildRunDetail,
	buildRunInput,
	createPayRunHandlers,
} from "./pay-run-handlers";

vi.mock("sonner", () => mockToast());

const PAGE_TIMEOUT = 15_000;

function renderPayRunRoutes(initialEntry: string) {
	return render(
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<AuthShellBoundary>
						<MemoryRouter initialEntries={[initialEntry]}>
							<Routes>
								<Route path="/pay-runs" element={<PayRunsPage />} />
								<Route path="/pay-runs/:runId" element={<PayRunDetailPage />} />
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

describe("Pay Runs list page", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"renders periods and runs, and navigates to detail on row click",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = createPayRunHandlers();
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs");

			expect(
				await screen.findByTestId("pay-runs-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(
				await screen.findByTestId("payroll-periods-list", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getAllByText("2026-07").length).toBeGreaterThan(0);
			expect(screen.getAllByText("2026-06").length).toBeGreaterThan(0);
			expect(screen.getByText("Regular")).toBeInTheDocument();
			expect(screen.getByText("Supplemental")).toBeInTheDocument();
			expect(screen.getByText("Draft")).toBeInTheDocument();
			expect(screen.getByText("Calculated")).toBeInTheDocument();

			fireEvent.click(screen.getByRole("button", { name: /Open pay run 2026-07/i }));
			expect(
				await screen.findByTestId("pay-run-detail-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"creates a payroll period successfully",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = createPayRunHandlers({
				periods: [buildPeriod({ id: "period-1", period_year: 2026, period_month: 7 })],
			});
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs");

			expect(
				await screen.findByTestId("pay-runs-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			fireEvent.click(screen.getByRole("button", { name: /^Period$/i }));

			expect(
				await screen.findByRole("heading", { name: "New Payroll Period" }),
			).toBeInTheDocument();
			fireEvent.change(screen.getByLabelText("Year"), { target: { value: "2026" } });
			fireEvent.change(screen.getByLabelText("Month"), { target: { value: "8" } });
			fireEvent.click(screen.getByRole("button", { name: "Create period" }));

			await waitFor(() => {
				expect(
					screen.queryByRole("heading", { name: "New Payroll Period" }),
				).not.toBeInTheDocument();
			});
			expect(await screen.findByText("2026-08")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it("surfaces 409 duplicate period as a friendly form error", async () => {
		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: payHandlers } = createPayRunHandlers({
			createPeriodError: {
				status: 409,
				body: {
					detail: "Payroll period already exists for this month",
					error: "ConflictError",
				},
			},
		});
		server.use(...authHandlers, ...payHandlers);

		renderDialog(<CreatePeriodDialog open onOpenChange={vi.fn()} />);

		expect(await screen.findByRole("heading", { name: "New Payroll Period" })).toBeInTheDocument();
		fireEvent.change(screen.getByLabelText("Year"), { target: { value: "2026" } });
		fireEvent.change(screen.getByLabelText("Month"), { target: { value: "7" } });
		fireEvent.click(screen.getByRole("button", { name: "Create period" }));

		expect(
			await screen.findByText("Payroll period already exists for this month"),
		).toBeInTheDocument();
	});

	it(
		"creates a pay run successfully",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = createPayRunHandlers({
				runs: [
					buildRun({
						id: "run-seed",
						period_id: "period-1",
						period_year: 2026,
						period_month: 7,
						run_type: "supplemental",
						status: "draft",
					}),
				],
			});
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs");

			expect(
				await screen.findByTestId("pay-runs-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			fireEvent.click(screen.getByRole("button", { name: /^Add$/i }));

			expect(await screen.findByRole("heading", { name: "New Pay Run" })).toBeInTheDocument();
			const dialog = screen.getByRole("dialog");
			expect(within(dialog).getByLabelText("Period")).toHaveTextContent("2026-07");
			expect(within(dialog).getByLabelText("Run Type")).toHaveTextContent("Regular");
			openBaseUiSelect(screen.getByLabelText("Run Type"));
			pickBaseUiOption("Regular");
			fireEvent.click(screen.getByRole("button", { name: "Create run" }));

			await waitFor(() => {
				expect(screen.queryByRole("heading", { name: "New Pay Run" })).not.toBeInTheDocument();
			});
			expect(await screen.findByText("Regular")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"hides create actions without create_run capability",
		async () => {
			const me = buildAuthMe({
				active_organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
					role: "payroll_reviewer",
					capabilities: ROLE_CAPABILITIES.payroll_reviewer,
				},
			});
			const { handlers: authHandlers } = createAuthHandlers({ me });
			const { handlers: payHandlers } = createPayRunHandlers();
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs");

			expect(
				await screen.findByText("You don't have access", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /^Period$/i })).not.toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /^Add$/i })).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});

describe("Pay run detail — calculate gating", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	async function renderDetailWithStatus(status: string) {
		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const detail = buildRunDetail({
			id: "run-1",
			period_id: "period-1",
			period_year: 2026,
			period_month: 7,
			status,
		});
		const { handlers: payHandlers } = createPayRunHandlers({
			runs: [
				buildRun({
					id: "run-1",
					period_id: "period-1",
					period_year: 2026,
					period_month: 7,
					status,
				}),
			],
			details: { "run-1": detail },
		});
		server.use(...authHandlers, ...payHandlers);
		renderPayRunRoutes("/pay-runs/run-1");
		expect(
			await screen.findByTestId("pay-run-detail-page", {}, { timeout: PAGE_TIMEOUT }),
		).toBeInTheDocument();
	}

	it.each([
		["draft", true],
		["calculated", true],
		["rejected", true],
		["submitted", false],
		["approved", false],
		["posted", false],
		["calculating", false],
	] as const)(
		"Calculate button for status %s (enabled=%s)",
		async (status, enabled) => {
			await renderDetailWithStatus(status);
			const button = await screen.findByRole("button", { name: "Calculate Pay Run" });
			if (enabled) {
				expect(button).toBeEnabled();
			} else {
				expect(button).toBeDisabled();
				expect(button).toHaveAttribute("title");
			}
		},
		PAGE_TIMEOUT,
	);

	it(
		"calculate success shows toast and refreshes detail totals",
		async () => {
			const { toast } = await import("sonner");
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = createPayRunHandlers({
				runs: [
					buildRun({
						id: "run-1",
						period_id: "period-1",
						period_year: 2026,
						period_month: 7,
						status: "draft",
					}),
				],
				details: {
					"run-1": buildRunDetail({
						id: "run-1",
						period_id: "period-1",
						period_year: 2026,
						period_month: 7,
						status: "draft",
						current_version: null,
					}),
				},
				calculateResult: {
					version_number: 2,
					engine_version: "engine-1.0.0",
					content_hash: "hash-calc-success",
					totals: {
						net_payable: "99000.00",
						gross_total: "112000.00",
					},
				},
			});
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs/run-1");

			expect(
				await screen.findByTestId("pay-run-detail-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.queryByTestId("pay-run-totals")).not.toBeInTheDocument();

			fireEvent.click(screen.getByRole("button", { name: "Calculate Pay Run" }));

			await waitFor(() => {
				expect(toast.success).toHaveBeenCalledWith("Pay run calculated");
			});

			expect(await screen.findByTestId("pay-run-totals")).toBeInTheDocument();
			expect(screen.getByText("Net Payable")).toBeInTheDocument();
			expect(screen.getByText("₹99,000.00")).toBeInTheDocument();
			expect(await screen.findByText("Calculated")).toBeInTheDocument();
			expect(screen.getByText("Engine engine-1.0.0")).toBeInTheDocument();
			expect(screen.getByText("v2")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"hides Calculate without create_run capability",
		async () => {
			const me = buildAuthMe({
				active_organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
					role: "payroll_reviewer",
					capabilities: ROLE_CAPABILITIES.payroll_reviewer,
				},
			});
			const { handlers: authHandlers } = createAuthHandlers({ me });
			const { handlers: payHandlers } = createPayRunHandlers();
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs/run-1");

			expect(
				await screen.findByText("You don't have access", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: "Calculate Pay Run" })).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});

describe("Pay run detail — inputs and totals", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"renders totals from mocked current_version",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = createPayRunHandlers({
				details: {
					"run-1": buildRunDetail({
						id: "run-1",
						period_id: "period-1",
						period_year: 2026,
						period_month: 7,
						status: "calculated",
						current_version: buildCurrentVersion({
							version_number: 3,
							engine_version: "engine-2.0.0",
							content_hash: "hash-from-detail",
							totals: {
								net_payable: "1234567.89",
								earnings_total: "2000000.00",
							},
						}),
					}),
				},
			});
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs/run-1");

			expect(
				await screen.findByTestId("pay-run-totals", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getByText("₹12,34,567.89")).toBeInTheDocument();
			expect(screen.getByText("₹20,00,000.00")).toBeInTheDocument();
			expect(screen.getByText("Engine engine-2.0.0")).toBeInTheDocument();
			expect(screen.getByText("v3")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"supports inputs CRUD while draft",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: employeeHandlers } = createEmployeeHandlers({
				employees: [
					{
						id: "emp-1",
						employee_number: "E-001",
						name: "Alice Example",
						sevarth_id: "SEV-001",
						retirement_regime: "gpf",
					},
				],
				details: {
					"emp-1": buildEmployeeDetail({
						id: "emp-1",
						employee_number: "E-001",
					}),
				},
			});
			const { handlers: payHandlers } = createPayRunHandlers({
				details: {
					"run-1": buildRunDetail({
						id: "run-1",
						period_id: "period-1",
						period_year: 2026,
						period_month: 7,
						status: "draft",
					}),
				},
				inputs: {
					"run-1": [
						buildRunInput({
							id: "input-1",
							run_id: "run-1",
							employee_id: "emp-1",
							component_code: "BASIC",
							amount: "1500.00",
							reason: "One-time bump",
						}),
					],
				},
			});
			server.use(...authHandlers, ...employeeHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs/run-1");

			expect(
				await screen.findByTestId("pay-run-detail-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(await screen.findByText("BASIC")).toBeInTheDocument();
			expect(screen.getByText("₹1,500.00")).toBeInTheDocument();
			expect(screen.getByRole("button", { name: /^Add$/i })).toBeInTheDocument();

			fireEvent.click(screen.getByRole("button", { name: /^Add$/i }));
			expect(await screen.findByRole("heading", { name: "Add Run Input" })).toBeInTheDocument();

			await waitFor(() => {
				expect(screen.getByLabelText("Employee")).toBeInTheDocument();
			});
			openBaseUiSelect(screen.getByLabelText("Employee"));
			pickBaseUiOption(/E-001/);
			fireEvent.change(screen.getByLabelText("Component Code"), { target: { value: "HRA" } });
			fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "2500.00" } });
			fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Housing adjust" } });
			fireEvent.click(screen.getByRole("button", { name: /^Add$/ }));

			await waitFor(() => {
				expect(screen.queryByRole("heading", { name: "Add Run Input" })).not.toBeInTheDocument();
			});
			expect(await screen.findByText("HRA")).toBeInTheDocument();

			fireEvent.click(screen.getByRole("button", { name: /Edit input BASIC/i }));
			expect(await screen.findByRole("heading", { name: "Edit Run Input" })).toBeInTheDocument();
			fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Updated reason" } });
			fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
			await waitFor(() => {
				expect(screen.queryByRole("heading", { name: "Edit Run Input" })).not.toBeInTheDocument();
			});
			expect(await screen.findByText("Updated reason")).toBeInTheDocument();

			fireEvent.click(screen.getByRole("button", { name: /Delete input HRA/i }));
			expect(await screen.findByRole("heading", { name: "Delete input?" })).toBeInTheDocument();
			fireEvent.click(screen.getByRole("button", { name: "Delete" }));
			await waitFor(() => {
				expect(screen.queryByText("HRA")).not.toBeInTheDocument();
			});
		},
		PAGE_TIMEOUT,
	);

	it(
		"hides input add/edit/delete when run is not draft",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = createPayRunHandlers({
				details: {
					"run-1": buildRunDetail({
						id: "run-1",
						period_id: "period-1",
						period_year: 2026,
						period_month: 7,
						status: "submitted",
					}),
				},
				inputs: {
					"run-1": [
						buildRunInput({
							id: "input-1",
							run_id: "run-1",
							employee_id: "emp-1",
							component_code: "BASIC",
							amount: "1500.00",
							reason: "One-time bump",
						}),
					],
				},
			});
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs/run-1");

			expect(
				await screen.findByTestId("pay-run-detail-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(await screen.findByText("BASIC")).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /^Add$/i })).not.toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /Edit input/i })).not.toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /Delete input/i })).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});

describe("Pay Runs capability gate", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"denies direct URL access without create_run",
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

			renderPayRunRoutes("/pay-runs");

			expect(
				await screen.findByText("You don't have access", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});
