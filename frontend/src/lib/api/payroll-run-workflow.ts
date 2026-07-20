/** Payroll run workflow commands: validate, submit, withdraw, approve, reject, post, reverse. */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { fetchJson } from "@/lib/api/http";
import { payrollRunQueryKeys } from "@/lib/api/payroll-runs";

/** Validation finding from POST /validate (OpenAPI returns untyped dict). */
export type ValidationFindingSeverity = "error" | "warning" | "info";

export type ValidationFinding = {
	code: string;
	severity: ValidationFindingSeverity;
	employee_ref: string | null;
	component_code: string | null;
	message: string;
	context?: Record<string, string>;
};

/** Shared summary shape returned by workflow/posting commands. */
export type PayrollRunWorkflowSummary = {
	id: string;
	status: string;
	current_version_number: number | null;
	content_hash: string | null;
};

export type PayrollRunValidateResult = PayrollRunWorkflowSummary & {
	findings: ValidationFinding[];
	blocking: boolean;
};

export type PayrollRunReverseResult = PayrollRunWorkflowSummary & {
	reversal_run_id: string;
};

export type WorkflowReasonBody = {
	reason?: string | null;
};

export type WorkflowCommandOptions = {
	idempotencyKey: string;
	reason?: string | null;
};

function workflowHeaders(idempotencyKey: string, withJson = true): Record<string, string> {
	const headers: Record<string, string> = {
		"Idempotency-Key": idempotencyKey,
	};
	if (withJson) {
		headers["Content-Type"] = "application/json";
	}
	return headers;
}

function invalidateRunQueries(queryClient: ReturnType<typeof useQueryClient>, runId: string): void {
	void queryClient.invalidateQueries({ queryKey: payrollRunQueryKeys.run(runId) });
	void queryClient.invalidateQueries({ queryKey: ["payroll-runs"] });
}

export function validatePayrollRun(runId: string) {
	return fetchJson<PayrollRunValidateResult>(`/api/payroll-runs/${runId}/validate`, {
		method: "POST",
	});
}

export function submitPayrollRun(runId: string, options: WorkflowCommandOptions) {
	const body: WorkflowReasonBody = { reason: options.reason ?? null };
	return fetchJson<PayrollRunWorkflowSummary>(`/api/payroll-runs/${runId}/submit`, {
		method: "POST",
		headers: workflowHeaders(options.idempotencyKey),
		body: JSON.stringify(body),
	});
}

export function withdrawPayrollRun(runId: string, options: WorkflowCommandOptions) {
	const body: WorkflowReasonBody = { reason: options.reason ?? null };
	return fetchJson<PayrollRunWorkflowSummary>(`/api/payroll-runs/${runId}/withdraw`, {
		method: "POST",
		headers: workflowHeaders(options.idempotencyKey),
		body: JSON.stringify(body),
	});
}

export function approvePayrollRun(runId: string, options: WorkflowCommandOptions) {
	const body: WorkflowReasonBody = { reason: options.reason ?? null };
	return fetchJson<PayrollRunWorkflowSummary>(`/api/payroll-runs/${runId}/approve`, {
		method: "POST",
		headers: workflowHeaders(options.idempotencyKey),
		body: JSON.stringify(body),
	});
}

export function rejectPayrollRun(runId: string, options: WorkflowCommandOptions) {
	const body: WorkflowReasonBody = { reason: options.reason ?? null };
	return fetchJson<PayrollRunWorkflowSummary>(`/api/payroll-runs/${runId}/reject`, {
		method: "POST",
		headers: workflowHeaders(options.idempotencyKey),
		body: JSON.stringify(body),
	});
}

export function postPayrollRun(runId: string, idempotencyKey: string) {
	return fetchJson<PayrollRunWorkflowSummary>(`/api/payroll-runs/${runId}/post`, {
		method: "POST",
		headers: workflowHeaders(idempotencyKey, false),
	});
}

export function reversePayrollRun(
	runId: string,
	options: { idempotencyKey: string; reason: string },
) {
	return fetchJson<PayrollRunReverseResult>(`/api/payroll-runs/${runId}/reverse`, {
		method: "POST",
		headers: workflowHeaders(options.idempotencyKey),
		body: JSON.stringify({ reason: options.reason }),
	});
}

export function useValidatePayrollRun(runId: string) {
	return useMutation({
		mutationFn: () => validatePayrollRun(runId),
	});
}

export function useSubmitPayrollRun(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (options: WorkflowCommandOptions) => submitPayrollRun(runId, options),
		onSuccess: () => invalidateRunQueries(queryClient, runId),
	});
}

export function useWithdrawPayrollRun(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (options: WorkflowCommandOptions) => withdrawPayrollRun(runId, options),
		onSuccess: () => invalidateRunQueries(queryClient, runId),
	});
}

export function useApprovePayrollRun(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (options: WorkflowCommandOptions) => approvePayrollRun(runId, options),
		onSuccess: () => invalidateRunQueries(queryClient, runId),
	});
}

export function useRejectPayrollRun(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (options: WorkflowCommandOptions) => rejectPayrollRun(runId, options),
		onSuccess: () => invalidateRunQueries(queryClient, runId),
	});
}

export function usePostPayrollRun(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (idempotencyKey: string) => postPayrollRun(runId, idempotencyKey),
		onSuccess: () => invalidateRunQueries(queryClient, runId),
	});
}

export function useReversePayrollRun(runId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (options: { idempotencyKey: string; reason: string }) =>
			reversePayrollRun(runId, options),
		onSuccess: () => invalidateRunQueries(queryClient, runId),
	});
}
