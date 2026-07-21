import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, AuthShellBoundary } from "@/contexts/AuthContext";
import { NAV_REGISTRY } from "@/lib/nav-registry";
import { queryClient } from "@/lib/query-client";
import { PRODUCT_REPORT_SHEETS } from "@/lib/reports/report-registry";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { buildAuthMe, buildRoleAuthMe } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { openBaseUiSelect, pickBaseUiOption } from "@/test/helpers";
import { buildPeriod, buildRun, createPayRunHandlers } from "@/test/msw/pay-run-handlers";
import {
	buildArtifact,
	createReportHandlers,
	defaultReportCatalog,
} from "@/test/msw/report-handlers";
import { server } from "@/test/msw-server";
import ReportSheetPage from "./ReportSheetPage";
import ReportsIndexRedirect from "./ReportsIndexRedirect";
import ReportsLayout from "./ReportsLayout";

vi.mock("@/lib/download", () => ({
	downloadBlob: vi.fn(),
}));

const PAGE_TIMEOUT = 15_000;

function renderReports(initialPath = "/reports/pay-bill") {
	return render(
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<AuthShellBoundary>
						<MemoryRouter initialEntries={[initialPath]}>
							<Routes>
								<Route path="/reports" element={<ReportsLayout />}>
									<Route index element={<ReportsIndexRedirect />} />
									<Route path=":reportSlug" element={<ReportSheetPage />} />
								</Route>
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

	it("FE product sheet keys are a subset of catalog product sheets", () => {
		const catalog = defaultReportCatalog();
		const productTypes = new Set(
			catalog.filter((item) => item.product_sheet).map((item) => item.report_type),
		);
		for (const sheet of PRODUCT_REPORT_SHEETS) {
			expect(productTypes.has(sheet.reportType)).toBe(true);
		}
		expect(PRODUCT_REPORT_SHEETS).toHaveLength(18);
	});

	it("nav children match product sheet slugs", () => {
		const reports = NAV_REGISTRY.find((entry) => entry.path === "/reports");
		expect(reports?.children?.map((child) => child.path)).toEqual(
			PRODUCT_REPORT_SHEETS.map((sheet) => `/reports/${sheet.slug}`),
		);
	});

	it(
		"index redirects to first product sheet and shows preview after run select",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = seedPostedRuns();
			const { handlers: reportHandlers } = createReportHandlers();
			server.use(...authHandlers, ...payHandlers, ...reportHandlers);

			renderReports("/reports");

			expect(
				await screen.findByTestId("reports-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();

			await selectPostedRun(/June 2026/);

			expect(
				await screen.findByTestId("report-sheet-pay_bill", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			const preview = await screen.findByTestId("report-preview-tables");
			expect(within(preview).getByText("Ada Lovelace")).toBeInTheDocument();
			expect(within(preview).getByText("100.00")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"export flow queues job then downloads via result.artifact_id",
		async () => {
			const { downloadBlob } = await import("@/lib/download");
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: payHandlers } = seedPostedRuns();
			let exportCount = 0;
			const { handlers: reportHandlers } = createReportHandlers({
				jobStatusSequence: ["queued", "running", "succeeded"],
				onExport: () => {
					exportCount += 1;
				},
			});
			server.use(...authHandlers, ...payHandlers, ...reportHandlers);

			renderReports("/reports/pay-bill");
			await screen.findByTestId("reports-page", {}, { timeout: PAGE_TIMEOUT });
			await selectPostedRun(/June 2026/);

			fireEvent.click(screen.getByRole("button", { name: /Export all report sheets/i }));

			await waitFor(
				() => {
					expect(exportCount).toBe(1);
					expect(downloadBlob).toHaveBeenCalled();
				},
				{ timeout: PAGE_TIMEOUT },
			);
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
						report_type: "pay_bill",
						posted_run_id: "run-a",
						size_bytes: 2048,
						created_at: "2026-07-18T11:00:00Z",
					}),
					buildArtifact({
						id: "art-2",
						report_type: "bank_rtgs_advice",
						posted_run_id: "run-b",
						size_bytes: 4096,
						created_at: "2026-07-18T10:00:00Z",
					}),
				],
			});
			server.use(...authHandlers, ...payHandlers, ...reportHandlers);

			renderReports("/reports/pay-bill");

			const artifacts = await screen.findByTestId(
				"artifacts-section",
				{},
				{ timeout: PAGE_TIMEOUT },
			);
			expect(await within(artifacts).findByText("pay_bill")).toBeInTheDocument();
			expect(within(artifacts).getByText("bank_rtgs_advice")).toBeInTheDocument();

			await selectPostedRun(/June 2026/);

			await waitFor(
				() => {
					expect(
						within(screen.getByTestId("artifacts-section")).queryByText("bank_rtgs_advice"),
					).not.toBeInTheDocument();
				},
				{ timeout: PAGE_TIMEOUT },
			);
			expect(
				within(screen.getByTestId("artifacts-section")).getByText("pay_bill"),
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

			renderReports("/reports/pay-bill");

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

			renderReports("/reports/pay-bill");

			expect(
				await screen.findByText("No Posted Runs Yet", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
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

			renderReports("/reports/pay-bill");

			expect(
				await screen.findByText("No Artifacts Yet", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});
