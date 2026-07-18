import { HttpResponse, http } from "msw";

import type {
	PayrollRunDetail,
	PayrollRunListItem,
	PayrollRunValidateResult,
	PayrollRunWorkflowSummary,
	ValidationFinding,
} from "@/lib/api/payroll-runs";

export type WorkflowHandlersOptions = {
	/** Mutable detail store shared with pay-run handlers when provided. */
	details?: Map<string, PayrollRunDetail>;
	runs?: Map<string, PayrollRunListItem>;
	validateResult?:
		| Partial<PayrollRunValidateResult>
		| ((runId: string) => PayrollRunValidateResult);
	validateError?: { status: number; body: Record<string, unknown> };
	commandError?: { status: number; body: Record<string, unknown> };
	/** Per-command error overrides. */
	commandErrors?: Partial<
		Record<
			"submit" | "withdraw" | "approve" | "reject" | "post" | "reverse",
			{ status: number; body: Record<string, unknown> }
		>
	>;
	onValidate?: (runId: string) => void;
	onSubmit?: (runId: string, body: unknown, headers: Headers) => void;
	onWithdraw?: (runId: string, body: unknown, headers: Headers) => void;
	onApprove?: (runId: string, body: unknown, headers: Headers) => void;
	onReject?: (runId: string, body: unknown, headers: Headers) => void;
	onPost?: (runId: string, headers: Headers) => void;
	onReverse?: (runId: string, body: unknown, headers: Headers) => void;
};

function summaryFromDetail(detail: PayrollRunDetail): PayrollRunWorkflowSummary {
	const version = detail.current_version as Record<string, unknown> | null;
	return {
		id: detail.id,
		status: detail.status,
		current_version_number:
			typeof version?.version_number === "number" ? version.version_number : null,
		content_hash: typeof version?.content_hash === "string" ? version.content_hash : null,
	};
}

function updateStatus(
	details: Map<string, PayrollRunDetail>,
	runs: Map<string, PayrollRunListItem> | undefined,
	runId: string,
	status: string,
	extra?: Record<string, unknown>,
): PayrollRunWorkflowSummary & Record<string, unknown> {
	const detail = details.get(runId);
	if (!detail) {
		throw new Error(`Missing detail for ${runId}`);
	}
	const nextDetail: PayrollRunDetail = {
		...detail,
		status,
		lock_version: detail.lock_version + 1,
		updated_at: "2026-07-18T14:00:00Z",
	};
	details.set(runId, nextDetail);
	const run = runs?.get(runId);
	if (run && runs) {
		runs.set(runId, {
			...run,
			status,
			lock_version: run.lock_version + 1,
			updated_at: nextDetail.updated_at,
		});
	}
	return { ...summaryFromDetail(nextDetail), ...extra };
}

export function buildFinding(
	overrides: Partial<ValidationFinding> & { code: string; severity: ValidationFinding["severity"] },
): ValidationFinding {
	return {
		code: overrides.code,
		severity: overrides.severity,
		employee_ref: overrides.employee_ref ?? null,
		component_code: overrides.component_code ?? null,
		message: overrides.message ?? overrides.code,
		context: overrides.context,
	};
}

export function createWorkflowHandlers(options: WorkflowHandlersOptions = {}) {
	const details = options.details ?? new Map<string, PayrollRunDetail>();
	const runs = options.runs;

	const resolveCommandError = (
		command: "submit" | "withdraw" | "approve" | "reject" | "post" | "reverse",
	) => options.commandErrors?.[command] ?? options.commandError;

	const handlers = [
		http.post("/api/payroll-runs/:runId/validate", ({ params }) => {
			const runId = String(params.runId);
			if (options.validateError) {
				return HttpResponse.json(options.validateError.body, {
					status: options.validateError.status,
				});
			}
			const detail = details.get(runId);
			if (!detail) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			options.onValidate?.(runId);

			if (typeof options.validateResult === "function") {
				return HttpResponse.json(options.validateResult(runId));
			}

			const findings = options.validateResult?.findings ?? [];
			const blocking =
				options.validateResult?.blocking ?? findings.some((f) => f.severity === "error");
			const result: PayrollRunValidateResult = {
				...summaryFromDetail(detail),
				findings,
				blocking,
				...options.validateResult,
			};
			return HttpResponse.json(result);
		}),

		http.post("/api/payroll-runs/:runId/submit", async ({ params, request }) => {
			const runId = String(params.runId);
			const err = resolveCommandError("submit");
			if (err) return HttpResponse.json(err.body, { status: err.status });
			const detail = details.get(runId);
			if (!detail) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			const body = await request.json().catch(() => null);
			options.onSubmit?.(runId, body, request.headers);
			return HttpResponse.json(updateStatus(details, runs, runId, "submitted"));
		}),

		http.post("/api/payroll-runs/:runId/withdraw", async ({ params, request }) => {
			const runId = String(params.runId);
			const err = resolveCommandError("withdraw");
			if (err) return HttpResponse.json(err.body, { status: err.status });
			const detail = details.get(runId);
			if (!detail) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			const body = await request.json().catch(() => null);
			options.onWithdraw?.(runId, body, request.headers);
			return HttpResponse.json(updateStatus(details, runs, runId, "calculated"));
		}),

		http.post("/api/payroll-runs/:runId/approve", async ({ params, request }) => {
			const runId = String(params.runId);
			const err = resolveCommandError("approve");
			if (err) return HttpResponse.json(err.body, { status: err.status });
			const detail = details.get(runId);
			if (!detail) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			const body = await request.json().catch(() => null);
			options.onApprove?.(runId, body, request.headers);
			return HttpResponse.json(updateStatus(details, runs, runId, "approved"));
		}),

		http.post("/api/payroll-runs/:runId/reject", async ({ params, request }) => {
			const runId = String(params.runId);
			const err = resolveCommandError("reject");
			if (err) return HttpResponse.json(err.body, { status: err.status });
			const detail = details.get(runId);
			if (!detail) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			const body = await request.json().catch(() => null);
			options.onReject?.(runId, body, request.headers);
			return HttpResponse.json(updateStatus(details, runs, runId, "rejected"));
		}),

		http.post("/api/payroll-runs/:runId/post", ({ params, request }) => {
			const runId = String(params.runId);
			const err = resolveCommandError("post");
			if (err) return HttpResponse.json(err.body, { status: err.status });
			const detail = details.get(runId);
			if (!detail) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			options.onPost?.(runId, request.headers);
			return HttpResponse.json(updateStatus(details, runs, runId, "posted"));
		}),

		http.post("/api/payroll-runs/:runId/reverse", async ({ params, request }) => {
			const runId = String(params.runId);
			const err = resolveCommandError("reverse");
			if (err) return HttpResponse.json(err.body, { status: err.status });
			const detail = details.get(runId);
			if (!detail) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			const body = await request.json().catch(() => null);
			options.onReverse?.(runId, body, request.headers);
			return HttpResponse.json(
				updateStatus(details, runs, runId, "reversed", {
					reversal_run_id: "reversal-run-1",
				}),
			);
		}),
	];

	return { handlers, details, runs };
}
