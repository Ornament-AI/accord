import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { queryClient } from "@/lib/query-client";
import { buildAuthMe, buildRoleAuthMe, ROLE_CAPABILITIES } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { server } from "@/test/msw-server";
import { renderApp } from "@/test/render-app";
import type { Capability } from "@/types/auth";

import {
	buildDashboardResponse,
	buildEmptyOrgDashboard,
	buildPostedRun,
	createDashboardHandlers,
} from "./dashboard-handlers";

// Warm the same module the router lazy-loads so Suspense does not stall tests.
import "@/pages/DashboardPage";

const PAGE_TIMEOUT = 15_000;

describe("Dashboard page", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"renders full dashboard data with stats, pipeline, chart, and variance",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: dashboardHandlers } = createDashboardHandlers();
			server.use(...authHandlers, ...dashboardHandlers);

			renderApp({ initialEntries: ["/"] });

			expect(
				await screen.findByTestId("dashboard-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(
				await screen.findByTestId("dashboard-content", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();

			const stats = screen.getByTestId("dashboard-stat-cards");
			expect(within(stats).getByText("47")).toBeInTheDocument();
			expect(within(stats).getByText("GPF 12 / NPS 30 / EPF 5")).toBeInTheDocument();
			expect(within(stats).getByText("₹11,20,000.00")).toBeInTheDocument();
			expect(within(stats).getByText("₹9,20,000.00")).toBeInTheDocument();
			expect(within(stats).getByText("₹1,20,000.00")).toBeInTheDocument();

			expect(screen.getByTestId("variance-gross")).toHaveAttribute("data-direction", "up");
			expect(screen.getByTestId("variance-net")).toHaveAttribute("data-direction", "up");

			expect(screen.getByTestId("pipeline-draft")).toHaveTextContent("1");
			expect(screen.getByTestId("pipeline-calculated")).toHaveTextContent("2");
			expect(screen.getByTestId("pipeline-submitted")).toHaveTextContent("1");
			expect(screen.getByTestId("pipeline-posted")).toHaveTextContent("5");

			expect(screen.getByTestId("current-period-run-status")).toHaveTextContent("Calculated");
			const runLink = screen.getByTestId("current-period-run-link");
			expect(runLink).toHaveAttribute("href", "/pay-runs/run-current");

			expect(
				await screen.findByTestId("posted-comparison-chart", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"shows empty-org CTAs when there are no employees or posted runs",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: dashboardHandlers } = createDashboardHandlers({
				data: buildEmptyOrgDashboard(),
			});
			server.use(...authHandlers, ...dashboardHandlers);

			renderApp({ initialEntries: ["/"] });

			expect(
				await screen.findByTestId("empty-employees", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getByRole("link", { name: /Go to employees/i })).toHaveAttribute(
				"href",
				"/employees",
			);

			expect(screen.getByTestId("empty-posted-runs")).toBeInTheDocument();
			expect(screen.getByRole("link", { name: /Go to pay runs/i })).toHaveAttribute(
				"href",
				"/pay-runs",
			);
			expect(screen.queryByTestId("posted-comparison-chart")).not.toBeInTheDocument();
			expect(screen.queryByTestId("variance-gross")).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"hides variance indicators when only one posted run exists",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: dashboardHandlers } = createDashboardHandlers({
				data: buildDashboardResponse({
					previous_posted: null,
					variance: null,
					latest_posted: buildPostedRun({
						run_id: "run-only",
						period: { year: 2026, month: 6 },
					}),
				}),
			});
			server.use(...authHandlers, ...dashboardHandlers);

			renderApp({ initialEntries: ["/"] });

			expect(
				await screen.findByTestId("dashboard-content", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.queryByTestId("variance-gross")).not.toBeInTheDocument();
			expect(screen.queryByTestId("variance-net")).not.toBeInTheDocument();
			expect(
				await screen.findByTestId("posted-comparison-chart", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"shows a welcome-only limited state without fetching dashboard data",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("auditor"),
			});
			const { handlers: dashboardHandlers, getFetchCount } = createDashboardHandlers();
			server.use(...authHandlers, ...dashboardHandlers);

			renderApp({ initialEntries: ["/"] });

			expect(
				await screen.findByTestId("dashboard-welcome", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getByText("Limited dashboard access")).toBeInTheDocument();
			expect(screen.queryByTestId("dashboard-content")).not.toBeInTheDocument();
			expect(screen.queryByTestId("dashboard-stat-cards")).not.toBeInTheDocument();

			await waitFor(() => {
				expect(getFetchCount()).toBe(0);
			});
		},
		PAGE_TIMEOUT,
	);

	it(
		"links recent artifacts to /reports",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: dashboardHandlers } = createDashboardHandlers({
				data: buildDashboardResponse({
					recent_artifacts: [
						{
							id: "art-link-1",
							report_type: "payroll_register.pay_bill",
							created_at: "2026-07-01T12:00:00",
						},
						{
							id: "art-link-2",
							report_type: "payments.bank_rtgs_advice",
							created_at: "2026-06-30T09:30:00",
						},
					],
				}),
			});
			server.use(...authHandlers, ...dashboardHandlers);

			renderApp({ initialEntries: ["/"] });

			expect(
				await screen.findByTestId("dashboard-recent-artifacts", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();

			const first = screen.getByTestId("artifact-link-art-link-1");
			const second = screen.getByTestId("artifact-link-art-link-2");
			expect(first).toHaveAttribute("href", "/reports");
			expect(second).toHaveAttribute("href", "/reports");
		},
		PAGE_TIMEOUT,
	);

	it(
		"fetches dashboard data for a member with view_master_data only",
		async () => {
			const capabilities = ["view_master_data"] as Capability[];
			const me = buildAuthMe({
				active_organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
					role: "payroll_reviewer",
					capabilities: [...ROLE_CAPABILITIES.payroll_reviewer],
				},
			});
			me.active_organization!.capabilities = capabilities;

			const { handlers: authHandlers } = createAuthHandlers({ me });
			const { handlers: dashboardHandlers, getFetchCount } = createDashboardHandlers();
			server.use(...authHandlers, ...dashboardHandlers);

			renderApp({ initialEntries: ["/"] });

			expect(
				await screen.findByTestId("dashboard-content", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			await waitFor(() => {
				expect(getFetchCount()).toBeGreaterThan(0);
			});
		},
		PAGE_TIMEOUT,
	);
});
