import { HttpResponse, http } from "msw";

import type { DashboardResponse } from "@/lib/api/dashboard";

export type DashboardHandlersOptions = {
	data?: DashboardResponse;
	error?: { status: number; body: Record<string, unknown> };
	/** When set, counts how many times GET /api/dashboard was called. */
	onFetch?: () => void;
};

export function buildPostedRun(
	overrides: Partial<DashboardResponse["latest_posted"]> & {
		run_id: string;
		period: { year: number; month: number };
	},
): NonNullable<DashboardResponse["latest_posted"]> {
	return {
		run_id: overrides.run_id,
		period: overrides.period,
		totals: overrides.totals ?? {
			earnings: "1000000.00",
			employer_contribution: "120000.00",
			gross: "1120000.00",
			deductions: "200000.00",
			net: "920000.00",
		},
		posted_at: overrides.posted_at ?? "2026-06-28T10:00:00",
	};
}

export function buildDashboardResponse(
	overrides: Partial<DashboardResponse> = {},
): DashboardResponse {
	const base: DashboardResponse = {
		headcount: {
			active_employees: 47,
			by_regime: { gpf: 12, nps: 30, epf: 5 },
		},
		current_period: {
			year: 2026,
			month: 7,
			run: { id: "run-current", status: "calculated", version_number: 2 },
		},
		latest_posted: buildPostedRun({
			run_id: "run-latest",
			period: { year: 2026, month: 6 },
			totals: {
				earnings: "1000000.00",
				employer_contribution: "120000.00",
				gross: "1120000.00",
				deductions: "200000.00",
				net: "920000.00",
			},
			posted_at: "2026-06-28T10:00:00",
		}),
		previous_posted: buildPostedRun({
			run_id: "run-previous",
			period: { year: 2026, month: 5 },
			totals: {
				earnings: "980000.00",
				employer_contribution: "118000.00",
				gross: "1098000.00",
				deductions: "195000.00",
				net: "903000.00",
			},
			posted_at: "2026-05-28T10:00:00",
		}),
		variance: {
			gross_delta: "22000.00",
			net_delta: "17000.00",
		},
		pipeline: {
			draft: 1,
			calculated: 2,
			submitted: 1,
			approved: 0,
			posted: 5,
			rejected: 0,
			reversed: 0,
		},
		recent_artifacts: [
			{
				id: "art-1",
				report_type: "payroll_register.pay_bill",
				created_at: "2026-07-01T12:00:00",
			},
			{
				id: "art-2",
				report_type: "payments.bank_rtgs_advice",
				created_at: "2026-06-30T09:30:00",
			},
			{
				id: "art-3",
				report_type: "retirement.gpf_mumbai",
				created_at: "2026-06-29T16:15:00",
			},
		],
	};

	return {
		...base,
		...overrides,
		headcount: overrides.headcount ?? base.headcount,
		current_period:
			overrides.current_period === undefined ? base.current_period : overrides.current_period,
		latest_posted:
			overrides.latest_posted === undefined ? base.latest_posted : overrides.latest_posted,
		previous_posted:
			overrides.previous_posted === undefined ? base.previous_posted : overrides.previous_posted,
		variance: overrides.variance === undefined ? base.variance : overrides.variance,
		pipeline: overrides.pipeline ?? base.pipeline,
		recent_artifacts: overrides.recent_artifacts ?? base.recent_artifacts,
	};
}

export function buildEmptyOrgDashboard(): DashboardResponse {
	return buildDashboardResponse({
		headcount: { active_employees: 0, by_regime: { gpf: 0, nps: 0, epf: 0 } },
		current_period: null,
		latest_posted: null,
		previous_posted: null,
		variance: null,
		pipeline: {
			draft: 0,
			calculated: 0,
			submitted: 0,
			approved: 0,
			posted: 0,
			rejected: 0,
			reversed: 0,
		},
		recent_artifacts: [],
	});
}

export function createDashboardHandlers(options: DashboardHandlersOptions = {}) {
	const data = options.data ?? buildDashboardResponse();
	let fetchCount = 0;

	const handlers = [
		http.get("/api/dashboard", () => {
			fetchCount += 1;
			options.onFetch?.();
			if (options.error) {
				return HttpResponse.json(options.error.body, { status: options.error.status });
			}
			return HttpResponse.json(data);
		}),
	];

	return {
		handlers,
		getFetchCount: () => fetchCount,
	};
}
