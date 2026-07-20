import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, AuthShellBoundary } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { buildPeriod, buildRun, createPayRunHandlers } from "@/pages/pay-runs/pay-run-handlers";
import { buildAuthMe, buildRoleAuthMe } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { openBaseUiSelect, pickBaseUiOption } from "@/test/helpers";
import { server } from "@/test/msw-server";

import ReportsPage from "./ReportsPage";
import { buildArtifact, createReportHandlers, defaultReportCatalog } from "./report-handlers";

vi.mock("@/lib/download", () => ({
	downloadBlob: vi.fn(),
}));

const PAGE_TIMEOUT = 15_000;

function renderReportsPage() {
	return render(
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<AuthShellBoundary>
						<MemoryRouter initialEntries={["/reports"]}>
							<Routes>
								<Route path="/reports" element={<ReportsPage />} />
							</Routes>
						</MemoryRouter>
					</AuthShellBoundary>
				</AuthProvider>
			</ThemeProvider>
		</QueryClientProvider>,
	);
}

function seedPostedRuns() {
	const period = buildPeriod({ id: "period-1", period_year: 2026, period_month: 6 });
	const runA = buildRun({
		id: "run-a",
		period_id: period.id,
		period_year: 2026,
		period_month: 6,
		status: "posted",
	});
	const runB = buildRun({
		id: "run-b",
		period_id: period.id,
		period_year: 2026,
		period_month: 5,
		status: "posted",
	});
	return createPayRunHandlers({
		periods: [period],
		runs: [runA, runB],
	});
}

async function selectPostedRun(label: RegExp | string) {
	openBaseUiSelect(screen.getByLabelText("Select Posted Run"));
	pickBaseUiOption(label);
}

describe("Reports page", () => {
	beforeEach(() => {
		queryClient.clear();
		vi.clearAllMocks();
	});

	it(
		"renders catalog grouped by report family",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = seedPostedRuns();
			const { handlers: reportHandlers } = createReportHandlers({
				catalog: defaultReportCatalog(),
			});
			server.use(...authHandlers, ...payHandlers, ...reportHandlers);

			renderReportsPage();

			expect(
				await screen.findByTestId("reports-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(
				await screen.findByTestId("report-family-payroll_register", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getByTestId("report-family-payments")).toBeInTheDocument();
			expect(screen.getByTestId("report-family-retirement")).toBeInTheDocument();
			expect(screen.getByTestId("report-family-statutory")).toBeInTheDocument();
			expect(screen.getByTestId("report-family-recovery")).toBeInTheDocument();
			expect(screen.getByTestId("report-family-accommodation")).toBeInTheDocument();
			expect(screen.getByTestId("report-family-approval")).toBeInTheDocument();

			const payrollGroup = screen.getByTestId("report-family-payroll_register");
			expect(within(payrollGroup).getByText("Pay Bill")).toBeInTheDocument();
			expect(within(payrollGroup).getByText("Treasury Face")).toBeInTheDocument();
			expect(within(payrollGroup).getByText("Payroll Register")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"full generate flow queued → running → succeeded shows Download",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = seedPostedRuns();
			const { handlers: reportHandlers } = createReportHandlers({
				jobStatusSequence: ["queued", "running", "succeeded"],
			});
			server.use(...authHandlers, ...payHandlers, ...reportHandlers);

			renderReportsPage();

			await screen.findByTestId("report-catalog", {}, { timeout: PAGE_TIMEOUT });
			await selectPostedRun(/June 2026/);

			const payBill = await screen.findByTestId("report-type-payroll_register.pay_bill");
			fireEvent.click(
				within(payBill).getByRole("button", {
					name: /Generate Excel for payroll_register.pay_bill/i,
				}),
			);

			expect(await screen.findByText("Queued…", {}, { timeout: PAGE_TIMEOUT })).toBeInTheDocument();

			expect(
				await screen.findByRole("button", { name: /^Download$/i }, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"failed job shows error and retry works",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = seedPostedRuns();

			let generateCount = 0;
			const { handlers: reportHandlers } = createReportHandlers({
				jobStatusSequence: ["failed"],
				jobError: "Template missing",
				onGenerate: () => {
					generateCount += 1;
				},
			});
			server.use(...authHandlers, ...payHandlers, ...reportHandlers);

			renderReportsPage();
			await screen.findByTestId("report-catalog", {}, { timeout: PAGE_TIMEOUT });
			await selectPostedRun(/June 2026/);

			const payBill = screen.getByTestId("report-type-payroll_register.pay_bill");
			fireEvent.click(
				within(payBill).getByRole("button", {
					name: /Generate Excel for payroll_register.pay_bill/i,
				}),
			);

			expect(
				await screen.findByText("Template missing", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(generateCount).toBe(1);

			fireEvent.click(screen.getByRole("button", { name: /^Retry$/i }));

			await waitFor(
				() => {
					expect(generateCount).toBe(2);
				},
				{ timeout: PAGE_TIMEOUT },
			);
			expect(
				await screen.findByText("Template missing", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"artifacts list renders and filters by selected run",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = seedPostedRuns();
			const { handlers: reportHandlers } = createReportHandlers({
				artifacts: [
					buildArtifact({
						id: "art-1",
						report_type: "payroll_register.pay_bill",
						posted_run_id: "run-a",
						size_bytes: 2048,
						created_at: "2026-07-18T11:00:00Z",
					}),
					buildArtifact({
						id: "art-2",
						report_type: "payments.bank_rtgs_advice",
						posted_run_id: "run-b",
						size_bytes: 4096,
						created_at: "2026-07-18T10:00:00Z",
					}),
				],
			});
			server.use(...authHandlers, ...payHandlers, ...reportHandlers);

			renderReportsPage();

			const artifacts = await screen.findByTestId(
				"artifacts-section",
				{},
				{ timeout: PAGE_TIMEOUT },
			);
			expect(await within(artifacts).findByText("payroll_register.pay_bill")).toBeInTheDocument();
			expect(within(artifacts).getByText("payments.bank_rtgs_advice")).toBeInTheDocument();
			expect(within(artifacts).getByText("2.0 KB")).toBeInTheDocument();

			await selectPostedRun(/June 2026/);

			await waitFor(
				() => {
					expect(
						within(screen.getByTestId("artifacts-section")).queryByText(
							"payments.bank_rtgs_advice",
						),
					).not.toBeInTheDocument();
				},
				{ timeout: PAGE_TIMEOUT },
			);
			expect(
				within(screen.getByTestId("artifacts-section")).getByText("payroll_register.pay_bill"),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"capability gate blocks without generate_reports",
		async () => {
			const me = buildAuthMe({
				organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
				},
				membership: {
					role: "payroll_preparer",
					capabilities: ["view_master_data", "create_run"],
				},
			});
			const { handlers: authHandlers } = createAuthHandlers({ me });
			const { handlers: payHandlers } = seedPostedRuns();
			const { handlers: reportHandlers } = createReportHandlers();
			server.use(...authHandlers, ...payHandlers, ...reportHandlers);

			renderReportsPage();

			expect(
				await screen.findByText("You Don't Have Access", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.queryByTestId("reports-page")).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"shows no-posted-runs empty state",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = createPayRunHandlers({
				periods: [buildPeriod({ id: "period-1", period_year: 2026, period_month: 6 })],
				runs: [
					buildRun({
						id: "run-draft",
						period_id: "period-1",
						period_year: 2026,
						period_month: 6,
						status: "draft",
					}),
				],
			});
			const { handlers: reportHandlers } = createReportHandlers();
			server.use(...authHandlers, ...payHandlers, ...reportHandlers);

			renderReportsPage();

			expect(
				await screen.findByText("No Posted Runs Yet", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.queryByTestId("report-catalog")).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"shows no artifacts empty state when none exist",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = seedPostedRuns();
			const { handlers: reportHandlers } = createReportHandlers({ artifacts: [] });
			server.use(...authHandlers, ...payHandlers, ...reportHandlers);

			renderReportsPage();

			expect(
				await screen.findByText("No Artifacts Yet", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});
