import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJson, fetchVoid } from "@/lib/api/http";
import type { components } from "@/types/api.generated";

export type PayrollPeriodCreate = components["schemas"]["PayrollPeriodCreate"];
export type PayrollPeriodResponse = components["schemas"]["PayrollPeriodResponse"];
export type PayrollRunCreate = components["schemas"]["PayrollRunCreate"];
export type PayrollRunListItem = components["schemas"]["PayrollRunListItem"];
export type PayrollRunDetail = components["schemas"]["PayrollRunDetail"];
export type PayrollRunInputResponse = components["schemas"]["PayrollRunInputResponse"];
export type PayrollRunInputUpsert = components["schemas"]["PayrollRunInputUpsert"];
export type RunType = components["schemas"]["RunType"];
export type InputKind = components["schemas"]["InputKind"];

export const RUN_TYPES: RunType[] = ["regular", "supplemental", "reversal"];
export const INPUT_KINDS: InputKind[] = ["exception", "override", "one_time"];

/** Backend-visible payroll run statuses (DB check constraint). */
export const PAYROLL_RUN_STATUSES = [
	"draft",
	"calculating",
	"calculated",
	"submitted",
	"approved",
	"rejected",
	"posted",
	"reversed",
] as const;

export type PayrollRunStatus = (typeof PAYROLL_RUN_STATUSES)[number];

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
};

export function periodLabel(year: number, month: number): string {
	return `${year}-${String(month).padStart(2, "0")}`;
}

export function runTypeLabel(value: string): string {
	return value
		.split("_")
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

export function inputKindLabel(value: string): string {
	return value
		.split("_")
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

export function statusLabel(value: string): string {
	return value
		.split("_")
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

/**
 * Format a canonical money string for display without parseFloat.
 * Accepts optional leading sign and up to 2 decimal places.
 */
export function formatCanonicalMoney(value: string | null | undefined): string {
	if (value == null || value === "") return "—";
	const trimmed = value.trim();
	const match = trimmed.match(/^(-?)(\d+)(?:\.(\d{1,2}))?$/);
	if (!match) return trimmed;

	const sign = match[1];
	const intPart = match[2];
	const frac = (match[3] ?? "00").padEnd(2, "0");

	let grouped = intPart;
	if (intPart.length > 3) {
		const last3 = intPart.slice(-3);
		let rest = intPart.slice(0, -3);
		const parts: string[] = [];
		while (rest.length > 2) {
			parts.unshift(rest.slice(-2));
			rest = rest.slice(0, -2);
		}
		if (rest) parts.unshift(rest);
		grouped = `${parts.join(",")},${last3}`;
	}

	return `\u20B9${sign}${grouped}.${frac}`;
}

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

function buildQueryString(
	params: Record<string, string | number | boolean | null | undefined>,
): string {
	const search = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value === undefined || value === null || value === "" || value === false) continue;
		search.set(key, String(value));
	}
	const qs = search.toString();
	return qs ? `?${qs}` : "";
}

export function listPayrollPeriods() {
	return fetchJson<PayrollPeriodResponse[]>("/api/payroll-periods");
}

export function createPayrollPeriod(body: PayrollPeriodCreate) {
	return fetchJson<PayrollPeriodResponse>("/api/payroll-periods", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function listPayrollRuns(filters: PayrollRunFilters = {}) {
	const qs = buildQueryString({
		period_id: filters.period_id,
		status: filters.status,
	});
	return fetchJson<PayrollRunListItem[]>(`/api/payroll-runs${qs}`);
}

export function createPayrollRun(body: PayrollRunCreate) {
	return fetchJson<PayrollRunListItem>("/api/payroll-runs", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function getPayrollRun(runId: string) {
	return fetchJson<PayrollRunDetail>(`/api/payroll-runs/${runId}`);
}

export function listPayrollRunInputs(runId: string) {
	return fetchJson<PayrollRunInputResponse[]>(`/api/payroll-runs/${runId}/inputs`);
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
		{
			method: "PUT",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(body),
		},
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

export function usePayrollRunInputs(runId: string | undefined) {
	return useQuery({
		queryKey: payrollRunQueryKeys.inputs(runId ?? ""),
		queryFn: () => listPayrollRunInputs(runId!),
		enabled: Boolean(runId),
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
		},
	});
}

export function useDeletePayrollRunInput(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (inputId: string) => deletePayrollRunInput(runId, inputId),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: payrollRunQueryKeys.inputs(runId) });
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
		},
	});
}
