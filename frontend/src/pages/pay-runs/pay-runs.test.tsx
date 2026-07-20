import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, AuthShellBoundary } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { buildAuthMe, buildRoleAuthMe, ROLE_CAPABILITIES } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { mockToast } from "@/test/helpers";
import { server } from "@/test/msw-server";

import { CreatePeriodDialog } from "./CreatePeriodDialog";
import PayRunDetailPage from "./PayRunDetailPage";
import PayRunsPage from "./PayRunsPage";
import {
	buildCurrentVersion,
	buildPeriod,
	buildRosterRow,
	buildRun,
	buildRunDetail,
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
		"renders the pay runs empty state",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = createPayRunHandlers({ periods: [], runs: [] });
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs");

			expect(
				await screen.findByText("No Payroll History", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getByText("Select Add to create the first payroll run.")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"renders runs and navigates to detail on row click",
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
				await screen.findByText("July 2026", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getByText("June 2026")).toBeInTheDocument();
			expect(screen.queryByRole("columnheader", { name: "Run Type" })).not.toBeInTheDocument();
			expect(screen.getByText("Draft")).toBeInTheDocument();
			expect(screen.getByText("Calculated")).toBeInTheDocument();

			fireEvent.click(screen.getByRole("button", { name: /Open pay run July 2026/i }));
			expect(
				await screen.findByTestId("pay-run-detail-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"opens the Add form, then creates and opens the selected month's pay run",
		async () => {
			const onCreatePeriod = vi.fn();
			const onCreateRun = vi.fn();
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = createPayRunHandlers({
				periods: [buildPeriod({ id: "period-1", period_year: 2026, period_month: 7 })],
				onCreatePeriod,
				onCreateRun,
			});
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs");

			expect(
				await screen.findByTestId("pay-runs-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.queryByText("Which payroll period are you running?")).not.toBeInTheDocument();
			fireEvent.click(screen.getByRole("button", { name: "Add" }));
			expect(await screen.findByRole("heading", { name: "Add Pay Run" })).toBeInTheDocument();
			fireEvent.click(screen.getByRole("button", { name: "Payroll Month" }));
			fireEvent.click(await screen.findByRole("button", { name: "Aug 2026" }));
			const continueButton = screen.getByRole("button", { name: "Continue" });
			await waitFor(() => expect(continueButton).toBeEnabled());
			fireEvent.click(continueButton);

			await waitFor(() =>
				expect(onCreatePeriod).toHaveBeenCalledWith({ period_year: 2026, period_month: 8 }),
			);
			await waitFor(() => expect(onCreateRun).toHaveBeenCalled());
			expect(onCreateRun).toHaveBeenCalledWith({ period_id: "period-new-2" });
			expect(
				await screen.findByTestId("pay-run-detail-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
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
		fireEvent.click(screen.getByRole("button", { name: "Create Period" }));

		expect(
			await screen.findByText("Payroll period already exists for this month"),
		).toBeInTheDocument();
	});

	it(
		"hides create actions without create_run capability",
		async () => {
			const me = buildAuthMe({
				organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
				},
				membership: {
					role: "payroll_reviewer",
					capabilities: ROLE_CAPABILITIES.payroll_reviewer,
				},
			});
			const { handlers: authHandlers } = createAuthHandlers({ me });
			const { handlers: payHandlers } = createPayRunHandlers();
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs");

			expect(
				await screen.findByText("You Don't Have Access", {}, { timeout: PAGE_TIMEOUT }),
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

	it(
		"selects employees and saves monthly payroll values from the table",
		async () => {
			const onReplaceRoster = vi.fn();
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
						status: "draft",
						roster_initialized: false,
					}),
				},
				rosters: {
					"run-1": [
						buildRosterRow({
							employee_id: "emp-1",
							employee_number: "E-001",
							employee_name: "Alice Example",
							selected: false,
						}),
					],
				},
				onReplaceRoster,
			});
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs/run-1");

			expect(
				await screen.findByTestId("payroll-run-roster", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.queryByPlaceholderText("Master")).not.toBeInTheDocument();
			expect(screen.getByRole("columnheader", { name: "Regime" })).toHaveClass("text-center");
			expect(screen.getByRole("columnheader", { name: "Paid Days" })).toHaveClass("text-center");
			expect(screen.getByRole("columnheader", { name: "Basic Pay" })).toHaveClass("text-right");
			expect(screen.getByLabelText("Paid Days for Alice Example")).toHaveClass("text-center");
			expect(screen.getByLabelText("Paid Days for Alice Example")).toBeDisabled();
			const menuActions = screen.getByTestId("pay-run-menu-actions");
			expect(within(menuActions).getByRole("button", { name: "Edit" })).toBeInTheDocument();
			fireEvent.click(screen.getByRole("button", { name: "Edit" }));
			expect(screen.getByLabelText("Paid Days for Alice Example")).toBeEnabled();
			fireEvent.change(screen.getByLabelText("Paid Days for Alice Example"), {
				target: { value: "29" },
			});
			expect(screen.getByRole("checkbox", { name: "Include Alice Example" })).toBeChecked();
			fireEvent.change(screen.getByLabelText("DA Percent for Alice Example"), {
				target: { value: "12.5" },
			});
			fireEvent.change(screen.getByLabelText("DA Difference for Alice Example"), {
				target: { value: "750" },
			});
			fireEvent.change(screen.getByLabelText("HRA Percent for Alice Example"), {
				target: { value: "18" },
			});
			fireEvent.change(screen.getByLabelText("Transport Amount for Alice Example"), {
				target: { value: "1200" },
			});
			fireEvent.click(screen.getByRole("button", { name: "Save" }));

			await waitFor(() =>
				expect(onReplaceRoster).toHaveBeenCalledWith("run-1", {
					employees: [
						{
							employee_id: "emp-1",
							payable_days: "29",
							da_percent: "12.5",
							da_difference: "750",
							hra_percent: "18",
							transport_amount: "1200",
						},
					],
				}),
			);
			expect(await screen.findByText("Created roster")).toBeInTheDocument();
			expect(screen.getByText("Dev Test User")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

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
		"disables Calculate while payroll table edits are unsaved",
		async () => {
			await renderDetailWithStatus("draft");
			const calculate = await screen.findByRole("button", { name: "Calculate Pay Run" });
			expect(calculate).toBeEnabled();

			fireEvent.click(screen.getByRole("button", { name: "Edit" }));
			expect(calculate).toBeDisabled();
			expect(calculate).toHaveAttribute(
				"title",
				"Save or cancel payroll table edits before calculating.",
			);

			fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
			expect(calculate).toBeEnabled();
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

			expect(await screen.findByText("Calculated")).toBeInTheDocument();
			expect(screen.getByText("Version 2")).toBeInTheDocument();
			expect(screen.queryByText(/Engine engine-/)).not.toBeInTheDocument();
			expect(screen.queryByText("Payroll results")).not.toBeInTheDocument();
			expect(screen.queryByText("Employee results")).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"hides Calculate without create_run capability",
		async () => {
			const me = buildAuthMe({
				organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
				},
				membership: {
					role: "payroll_reviewer",
					capabilities: ROLE_CAPABILITIES.payroll_reviewer,
				},
			});
			const { handlers: authHandlers } = createAuthHandlers({ me });
			const { handlers: payHandlers } = createPayRunHandlers();
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs/run-1");

			expect(
				await screen.findByText("You Don't Have Access", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: "Calculate Pay Run" })).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});

describe("Pay run detail — results and adjustments", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"keeps calculated output in the main roster table",
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
				await screen.findByTestId("payroll-run-roster", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getByText("Version 3")).toBeInTheDocument();
			expect(screen.queryByText(/Engine engine-/)).not.toBeInTheDocument();
			expect(screen.queryByText(/Hash hash-/)).not.toBeInTheDocument();
			expect(screen.getByRole("columnheader", { name: "Total" })).toBeInTheDocument();
			// Calculated runs show immutable net payable from results, not the roster preview.
			expect(await screen.findByText("₹59,000.00")).toBeInTheDocument();
			expect(screen.getByText("₹40,000.00")).toBeInTheDocument();
			expect(screen.queryByText("Payroll results")).not.toBeInTheDocument();
			expect(screen.queryByText("Employee results")).not.toBeInTheDocument();
			expect(screen.getByRole("heading", { name: "Change History" })).toBeInTheDocument();
			expect(screen.getByText("No Changes Yet")).toBeInTheDocument();
			expect(
				screen.queryByText("Saved edits to employee payroll values for this run."),
			).not.toBeInTheDocument();
			expect(
				screen.queryByText("No changes yet. Saved inline edits will appear here."),
			).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"shows saved roster history and hides Edit when the run is not draft",
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
				rosterHistory: {
					"run-1": [
						{
							id: "history-1",
							action: "Updated roster",
							changed_employees: 2,
							selected_employees: 12,
							changed_fields: ["Paid Days", "HRA %"],
							actor_name: "Payroll Administrator",
							created_at: "2026-07-18T12:30:00Z",
						},
					],
				},
			});
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs/run-1");

			expect(
				await screen.findByTestId("pay-run-detail-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(await screen.findByText("Updated roster")).toBeInTheDocument();
			expect(screen.getByText("Paid Days, HRA %")).toBeInTheDocument();
			expect(screen.getByText("Payroll Administrator")).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
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
				organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
				},
				membership: {
					role: "report_releaser",
					capabilities: ROLE_CAPABILITIES.report_releaser,
				},
			});
			const { handlers } = createAuthHandlers({ me });
			server.use(...handlers);

			renderPayRunRoutes("/pay-runs");

			expect(
				await screen.findByText("You Don't Have Access", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});

describe("Pay run detail — roster integrity", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"never shows the draft preview total for non-draft runs when results are unavailable",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			// Submitted run with no calculated version: the results endpoint 409s.
			const { handlers: payHandlers } = createPayRunHandlers({
				details: {
					"run-1": buildRunDetail({
						id: "run-1",
						period_id: "period-1",
						period_year: 2026,
						period_month: 7,
						status: "submitted",
						current_version: null,
					}),
				},
				rosters: {
					"run-1": [
						buildRosterRow({
							employee_id: "emp-1",
							employee_number: "E-001",
							employee_name: "Alice Example",
							basic_pay: "50000.00",
							payable_days: "31.00",
							transport_amount: "3000.00",
						}),
					],
				},
			});
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs/run-1");

			expect(
				await screen.findByTestId("payroll-run-roster", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			// The draft preview for these inputs would be prorated basic + transport
			// (₹50,000.00 + ₹3,000.00 = ₹53,000.00); a non-draft run must render a
			// blank total instead of surfacing that estimate. Basic Pay (₹50,000.00)
			// is a factual column and is expected to remain visible.
			expect(screen.queryByText("₹53,000.00", { selector: "td *" })).not.toBeInTheDocument();
			const totalHeader = screen.getByRole("columnheader", { name: "Total" });
			expect(totalHeader).toBeInTheDocument();
			expect(screen.getAllByText("—").length).toBeGreaterThan(0);
		},
		PAGE_TIMEOUT,
	);

	it(
		"surfaces ineligible saved employees: deselect-only, no editing, save blocked",
		async () => {
			const onReplaceRoster = vi.fn();
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
						status: "draft",
						roster_initialized: true,
					}),
				},
				rosters: {
					"run-1": [
						buildRosterRow({
							employee_id: "emp-1",
							employee_number: "E-001",
							employee_name: "Alice Example",
							selected: true,
						}),
						buildRosterRow({
							employee_id: "emp-2",
							employee_number: "E-002",
							employee_name: "Gone Employee",
							selected: true,
							eligible: false,
						}),
					],
				},
				onReplaceRoster,
			});
			server.use(...authHandlers, ...payHandlers);

			renderPayRunRoutes("/pay-runs/run-1");

			expect(
				await screen.findByTestId("payroll-run-roster", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getByText("No active profile")).toBeInTheDocument();

			fireEvent.click(screen.getByRole("button", { name: "Edit" }));
			// Ineligible rows stay read-only even in edit mode.
			expect(screen.getByLabelText("Paid Days for Gone Employee")).toBeDisabled();
			expect(screen.getByLabelText("Paid Days for Alice Example")).toBeEnabled();

			// Edit an eligible row to enable Save (dirty) without touching the
			// ineligible one, which stays selected.
			fireEvent.change(screen.getByLabelText("Paid Days for Alice Example"), {
				target: { value: "29" },
			});

			// Saving while an ineligible employee is selected is blocked client-side.
			// sonner is mocked in this suite, so assert on the toast spy rather than
			// looking for the message in the DOM.
			const { toast } = await import("sonner");
			fireEvent.click(screen.getByRole("button", { name: "Save" }));
			await waitFor(() =>
				expect(toast.error).toHaveBeenCalledWith(
					expect.stringContaining("no active profile for this period and must be deselected"),
				),
			);
			expect(onReplaceRoster).not.toHaveBeenCalled();

			// Deselecting is still allowed; once deselected the checkbox locks.
			const goneCheckbox = screen.getByRole("checkbox", { name: "Include Gone Employee" });
			expect(goneCheckbox).toBeEnabled();
			fireEvent.click(goneCheckbox);
			await waitFor(() =>
				expect(screen.getByRole("checkbox", { name: "Include Gone Employee" })).not.toBeChecked(),
			);
			// Base UI marks a locked checkbox with aria-disabled rather than the
			// native disabled attribute.
			expect(screen.getByRole("checkbox", { name: "Include Gone Employee" })).toHaveAttribute(
				"aria-disabled",
				"true",
			);

			fireEvent.click(screen.getByRole("button", { name: "Save" }));
			await waitFor(() =>
				expect(onReplaceRoster).toHaveBeenCalledWith("run-1", {
					employees: [expect.objectContaining({ employee_id: "emp-1" })],
				}),
			);
		},
		PAGE_TIMEOUT,
	);
});
