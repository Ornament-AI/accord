import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJson, fetchVoid, jsonRequest } from "@/lib/api/http";
import { buildQueryString } from "@/lib/api/query-utils";
import type { components } from "@/types/api.generated";

export type PayrollPeriodCreate = components["schemas"]["PayrollPeriodCreate"];
export type PayrollPeriodResponse = components["schemas"]["PayrollPeriodResponse"];
export type PayrollRunCreate = components["schemas"]["PayrollRunCreate"];
export type PayrollRunListItem = components["schemas"]["PayrollRunListItem"];
export type PayrollRunDetail = components["schemas"]["PayrollRunDetail"];
export type PayrollRunInputResponse = components["schemas"]["PayrollRunInputResponse"];
export type PayrollRunInputUpsert = components["schemas"]["PayrollRunInputUpsert"];
export type PayrollRunEmployeeResponse = components["schemas"]["PayrollRunEmployeeResponse"];
export type PayrollRunRosterUpdate = components["schemas"]["PayrollRunRosterUpdate"];
export type PayrollRunRosterHistoryResponse =
	components["schemas"]["PayrollRunRosterHistoryResponse"];
export type PayrollRunResults = components["schemas"]["RunResultsResponse"];
export type InputKind = components["schemas"]["InputKind"];
export type PayrollRunReportMetadata = components["schemas"]["PayrollRunReportMetadata"] & {
	token_number?: string | null;
	token_date?: string | null;
	voucher_number?: string | null;
	voucher_date?: string | null;
};
export type ReportReadinessResponse = components["schemas"]["ReportReadinessResponse"];

export const INPUT_KINDS: InputKind[] = ["exception", "override", "one_time"];

/**
 * Mirrors backend `calculate_run_command` / run-version totals payload.
 * OpenAPI types calculate as an untyped dict; money values are canonical strings.
 */
export type PayrollRunTotals = {
	earnings_total?: string;
	employer_contribution_total?: string;
	gross_adjustment_total?: string;
	gross_total?: string;
	ag_deduction_total?: string;
	treasury_deduction_total?: string;
	external_recovery_total?: string;
	deductions_total?: string;
	net_payable?: string;
	[key: string]: string | undefined;
};

/**
 * Mirrors backend calculate response / current_version shape (not fully typed in OpenAPI).
 */
export type PayrollRunCalculateResult = {
	run_id: string;
	version_id: string;
	version_number: number;
	content_hash: string;
	engine_version: string;
	totals: PayrollRunTotals;
};

export type PayrollRunFilters = {
	period_id?: string | null;
	status?: string | null;
};

export const payrollRunQueryKeys = {
	periods: () => ["payroll-periods"] as const,
	runs: (filters: PayrollRunFilters = {}) => ["payroll-runs", filters] as const,
	run: (runId: string) => ["payroll-run", runId] as const,
	inputs: (runId: string) => ["payroll-run-inputs", runId] as const,
	roster: (runId: string) => ["payroll-run-roster", runId] as const,
	rosterHistory: (runId: string) => ["payroll-run-roster-history", runId] as const,
	results: (runId: string) => ["payroll-run-results", runId] as const,
	reportReadiness: (runId: string) => ["payroll-run-report-readiness", runId] as const,
};

export function isCalculateAllowedStatus(status: string): boolean {
	return status === "draft" || status === "calculated" || status === "rejected";
}

export function isDraftStatus(status: string): boolean {
	return status === "draft";
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asOptionalString(value: unknown): string | undefined {
	return typeof value === "string" ? value : undefined;
}

function asOptionalNumber(value: unknown): number | undefined {
	return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

/** Best-effort parse of `current_version` / calculate payload fields used by the UI. */
export function parsePayrollRunVersion(value: unknown): PayrollRunCalculateResult | null {
	if (!isRecord(value)) return null;

	const versionNumber = asOptionalNumber(value.version_number);
	const engineVersion = asOptionalString(value.engine_version);
	const contentHash = asOptionalString(value.content_hash);
	const runId = asOptionalString(value.run_id) ?? "";
	const versionId = asOptionalString(value.version_id) ?? "";

	let totals: PayrollRunTotals = {};
	if (isRecord(value.totals)) {
		const next: PayrollRunTotals = {};
		for (const [key, entry] of Object.entries(value.totals)) {
			if (typeof entry === "string") next[key] = entry;
		}
		totals = next;
	}

	if (
		versionNumber === undefined &&
		engineVersion === undefined &&
		contentHash === undefined &&
		Object.keys(totals).length === 0
	) {
		return null;
	}

	return {
		run_id: runId,
		version_id: versionId,
		version_number: versionNumber ?? 0,
		engine_version: engineVersion ?? "",
		content_hash: contentHash ?? "",
		totals,
	};
}

export function listPayrollPeriods() {
	return fetchJson<PayrollPeriodResponse[]>("/api/payroll-periods");
}

export function createPayrollPeriod(body: PayrollPeriodCreate) {
	return fetchJson<PayrollPeriodResponse>("/api/payroll-periods", jsonRequest("POST", body));
}

export function listPayrollRuns(filters: PayrollRunFilters = {}) {
	const qs = buildQueryString({
		period_id: filters.period_id,
		status: filters.status,
	});
	return fetchJson<PayrollRunListItem[]>(`/api/payroll-runs${qs}`);
}

export function createPayrollRun(body: PayrollRunCreate) {
	return fetchJson<PayrollRunListItem>("/api/payroll-runs", jsonRequest("POST", body));
}

export function getPayrollRun(runId: string) {
	return fetchJson<PayrollRunDetail>(`/api/payroll-runs/${runId}`);
}

export function updatePayrollRunReportMetadata(runId: string, body: PayrollRunReportMetadata) {
	return fetchJson<PayrollRunReportMetadata>(
		`/api/payroll-runs/${runId}/report-metadata`,
		jsonRequest("PUT", body),
	);
}

export function getPayrollRunReportReadiness(runId: string) {
	return fetchJson<ReportReadinessResponse>(`/api/payroll-runs/${runId}/report-readiness`);
}

export function listPayrollRunRoster(runId: string) {
	return fetchJson<PayrollRunEmployeeResponse[]>(`/api/payroll-runs/${runId}/roster`);
}

export function listPayrollRunRosterHistory(runId: string) {
	return fetchJson<PayrollRunRosterHistoryResponse[]>(`/api/payroll-runs/${runId}/roster-history`);
}

export function replacePayrollRunRoster(runId: string, body: PayrollRunRosterUpdate) {
	return fetchJson<PayrollRunEmployeeResponse[]>(
		`/api/payroll-runs/${runId}/roster`,
		jsonRequest("PUT", body),
	);
}

export function getPayrollRunResults(runId: string) {
	return fetchJson<PayrollRunResults>(`/api/payroll-runs/${runId}/results`);
}

export function upsertPayrollRunInput(
	runId: string,
	employeeId: string,
	componentCode: string,
	body: PayrollRunInputUpsert,
) {
	const encodedCode = encodeURIComponent(componentCode);
	return fetchJson<PayrollRunInputResponse>(
		`/api/payroll-runs/${runId}/inputs/${employeeId}/${encodedCode}`,
		jsonRequest("PUT", body),
	);
}

export function deletePayrollRunInput(runId: string, inputId: string) {
	return fetchVoid(`/api/payroll-runs/${runId}/inputs/${inputId}`, {
		method: "DELETE",
	});
}

export function calculatePayrollRun(runId: string) {
	return fetchJson<PayrollRunCalculateResult>(`/api/payroll-runs/${runId}/calculate`, {
		method: "POST",
	});
}

export function usePayrollPeriods() {
	return useQuery({
		queryKey: payrollRunQueryKeys.periods(),
		queryFn: listPayrollPeriods,
	});
}

export function useCreatePayrollPeriod() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: createPayrollPeriod,
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: payrollRunQueryKeys.periods() });
		},
	});
}

export function usePayrollRuns(filters: PayrollRunFilters = {}) {
	return useQuery({
		queryKey: payrollRunQueryKeys.runs(filters),
		queryFn: () => listPayrollRuns(filters),
	});
}

export function useCreatePayrollRun() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: createPayrollRun,
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: ["payroll-runs"] });
		},
	});
}

export function usePayrollRun(runId: string | undefined) {
	return useQuery({
		queryKey: payrollRunQueryKeys.run(runId ?? ""),
		queryFn: () => getPayrollRun(runId!),
		enabled: Boolean(runId),
	});
}

export function useUpdatePayrollRunReportMetadata(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (body: PayrollRunReportMetadata) => updatePayrollRunReportMetadata(runId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: payrollRunQueryKeys.run(runId) });
			void queryClient.invalidateQueries({ queryKey: payrollRunQueryKeys.reportReadiness(runId) });
		},
	});
}

export function usePayrollRunReportReadiness(runId: string | undefined) {
	return useQuery({
		queryKey: payrollRunQueryKeys.reportReadiness(runId ?? ""),
		queryFn: () => getPayrollRunReportReadiness(runId!),
		enabled: Boolean(runId),
	});
}

export function usePayrollRunRoster(runId: string | undefined) {
	return useQuery({
		queryKey: payrollRunQueryKeys.roster(runId ?? ""),
		queryFn: () => listPayrollRunRoster(runId!),
		enabled: Boolean(runId),
	});
}

export function usePayrollRunRosterHistory(runId: string | undefined) {
	return useQuery({
		queryKey: payrollRunQueryKeys.rosterHistory(runId ?? ""),
		queryFn: () => listPayrollRunRosterHistory(runId!),
		enabled: Boolean(runId),
	});
}

export function useReplacePayrollRunRoster(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (body: PayrollRunRosterUpdate) => replacePayrollRunRoster(runId, body),
		onSuccess: (data) => {
			queryClient.setQueryData(payrollRunQueryKeys.roster(runId), data);
			void queryClient.invalidateQueries({ queryKey: payrollRunQueryKeys.rosterHistory(runId) });
			void queryClient.invalidateQueries({ queryKey: payrollRunQueryKeys.run(runId) });
			void queryClient.invalidateQueries({ queryKey: payrollRunQueryKeys.results(runId) });
		},
	});
}

export function usePayrollRunResults(runId: string | undefined, enabled: boolean) {
	return useQuery({
		queryKey: payrollRunQueryKeys.results(runId ?? ""),
		queryFn: () => getPayrollRunResults(runId!),
		enabled: Boolean(runId) && enabled,
	});
}

export function useUpsertPayrollRunInput(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({
			employeeId,
			componentCode,
			body,
		}: {
			employeeId: string;
			componentCode: string;
			body: PayrollRunInputUpsert;
		}) => upsertPayrollRunInput(runId, employeeId, componentCode, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: payrollRunQueryKeys.inputs(runId) });
			void queryClient.invalidateQueries({ queryKey: payrollRunQueryKeys.results(runId) });
		},
	});
}

export function useCalculatePayrollRun(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: () => calculatePayrollRun(runId),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: payrollRunQueryKeys.run(runId) });
			void queryClient.invalidateQueries({ queryKey: ["payroll-runs"] });
			void queryClient.invalidateQueries({ queryKey: payrollRunQueryKeys.inputs(runId) });
			void queryClient.invalidateQueries({ queryKey: payrollRunQueryKeys.results(runId) });
			void queryClient.invalidateQueries({
				queryKey: payrollRunQueryKeys.reportReadiness(runId),
			});
		},
	});
}
