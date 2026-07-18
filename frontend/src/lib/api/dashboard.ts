import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "@/lib/api/http";

export type DashboardRegimeBreakdown = {
	gpf: number;
	nps: number;
	epf: number;
};

export type DashboardHeadcount = {
	active_employees: number;
	by_regime: DashboardRegimeBreakdown;
};

export type DashboardCurrentPeriodRun = {
	id: string;
	status: string;
	version_number?: number;
};

export type DashboardCurrentPeriod = {
	year: number;
	month: number;
	run: DashboardCurrentPeriodRun | null;
};

export type DashboardPostedTotals = {
	earnings: string;
	employer_contribution: string;
	gross: string;
	deductions: string;
	net: string;
};

export type DashboardPostedRun = {
	run_id: string;
	period: { year: number; month: number };
	totals: DashboardPostedTotals;
	posted_at: string;
};

export type DashboardVariance = {
	gross_delta: string;
	net_delta: string;
};

export type DashboardPipeline = {
	draft: number;
	calculated: number;
	submitted: number;
	approved: number;
	posted: number;
	rejected: number;
	reversed: number;
};

export type DashboardRecentArtifact = {
	id: string;
	report_type: string;
	created_at: string;
};

export type DashboardResponse = {
	headcount: DashboardHeadcount;
	current_period: DashboardCurrentPeriod | null;
	latest_posted: DashboardPostedRun | null;
	previous_posted: DashboardPostedRun | null;
	variance: DashboardVariance | null;
	pipeline: DashboardPipeline;
	recent_artifacts: DashboardRecentArtifact[];
};

export const dashboardQueryKeys = {
	all: () => ["dashboard"] as const,
	summary: () => ["dashboard", "summary"] as const,
};

export function getDashboard() {
	return fetchJson<DashboardResponse>("/api/dashboard");
}

export function useDashboard(options?: { enabled?: boolean }) {
	return useQuery({
		queryKey: dashboardQueryKeys.summary(),
		queryFn: getDashboard,
		enabled: options?.enabled ?? true,
	});
}
