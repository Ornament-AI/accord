import { HttpResponse, http } from "msw";
import type {
	PayrollPeriodCreate,
	PayrollPeriodResponse,
	PayrollRunCalculateResult,
	PayrollRunCreate,
	PayrollRunDetail,
	PayrollRunEmployeeResponse,
	PayrollRunInputResponse,
	PayrollRunInputUpsert,
	PayrollRunListItem,
	PayrollRunResults,
	PayrollRunRosterHistoryResponse,
	PayrollRunRosterUpdate,
	PayrollRunTotals,
} from "@/lib/api/payroll-runs";
import type { components } from "@/types/api.generated";

export type PayRunHandlersOptions = {
	periods?: PayrollPeriodResponse[];
	runs?: PayrollRunListItem[];
	details?: Record<string, PayrollRunDetail>;
	inputs?: Record<string, PayrollRunInputResponse[]>;
	results?: Record<string, PayrollRunResults>;
	rosters?: Record<string, PayrollRunEmployeeResponse[]>;
	rosterHistory?: Record<string, PayrollRunRosterHistoryResponse[]>;
	/** When set, POST /api/payroll-periods returns this status/body (e.g. 409). */
	createPeriodError?: { status: number; body: Record<string, unknown> };
	/** When set, POST /api/payroll-runs returns this status/body. */
	createRunError?: { status: number; body: Record<string, unknown> };
	/** When set, POST .../calculate returns this status/body. */
	calculateError?: { status: number; body: Record<string, unknown> };
	/** Override calculate success payload (merged into defaults). */
	calculateResult?: Partial<PayrollRunCalculateResult>;
	onCreatePeriod?: (body: PayrollPeriodCreate) => void;
	onCreateRun?: (body: PayrollRunCreate) => void;
	onReplaceRoster?: (runId: string, body: PayrollRunRosterUpdate) => void;
	onCalculate?: (runId: string) => void;
	onUpsertInput?: (
		runId: string,
		employeeId: string,
		componentCode: string,
		body: PayrollRunInputUpsert,
	) => void;
	onDeleteInput?: (runId: string, inputId: string) => void;
};

const DEFAULT_TOTALS: PayrollRunTotals = {
	earnings_total: "100000.00",
	employer_contribution_total: "12000.00",
	gross_adjustment_total: "0.00",
	gross_total: "112000.00",
	ag_deduction_total: "5000.00",
	treasury_deduction_total: "8000.00",
	external_recovery_total: "0.00",
	deductions_total: "13000.00",
	net_payable: "99000.00",
};

export function buildPeriod(
	overrides: Partial<PayrollPeriodResponse> & {
		id: string;
		period_year: number;
		period_month: number;
	},
): PayrollPeriodResponse {
	const now = "2026-01-15T10:00:00Z";
	return {
		id: overrides.id,
		period_year: overrides.period_year,
		period_month: overrides.period_month,
		status: overrides.status ?? "open",
		created_at: overrides.created_at ?? now,
		updated_at: overrides.updated_at ?? now,
	};
}

export function buildRun(
	overrides: Partial<PayrollRunListItem> & {
		id: string;
		period_id: string;
		period_year: number;
		period_month: number;
	},
): PayrollRunListItem {
	const now = "2026-01-15T10:00:00Z";
	return {
		id: overrides.id,
		period_id: overrides.period_id,
		period_year: overrides.period_year,
		period_month: overrides.period_month,
		status: overrides.status ?? "draft",
		lock_version: overrides.lock_version ?? 1,
		created_at: overrides.created_at ?? now,
		updated_at: overrides.updated_at ?? now,
	};
}

export function buildRunDetail(
	overrides: Partial<PayrollRunDetail> & {
		id: string;
		period_id: string;
		period_year: number;
		period_month: number;
	},
): PayrollRunDetail {
	const now = "2026-01-15T10:00:00Z";
	return {
		id: overrides.id,
		period_id: overrides.period_id,
		period_year: overrides.period_year,
		period_month: overrides.period_month,
		period_status: overrides.period_status ?? "open",
		status: overrides.status ?? "draft",
		current_version: overrides.current_version ?? null,
		lock_version: overrides.lock_version ?? 1,
		roster_initialized: overrides.roster_initialized ?? true,
		created_at: overrides.created_at ?? now,
		updated_at: overrides.updated_at ?? now,
	};
}

export function buildRunInput(
	overrides: Partial<PayrollRunInputResponse> & {
		id: string;
		run_id: string;
		employee_id: string;
		component_code: string;
	},
): PayrollRunInputResponse {
	const now = "2026-01-15T10:00:00Z";
	return {
		id: overrides.id,
		run_id: overrides.run_id,
		employee_id: overrides.employee_id,
		component_code: overrides.component_code,
		input_kind: overrides.input_kind ?? "exception",
		amount: overrides.amount !== undefined ? overrides.amount : "1000.00",
		rate: overrides.rate !== undefined ? overrides.rate : null,
		reason: overrides.reason ?? "Adjustment",
		service_period_start: overrides.service_period_start ?? null,
		service_period_end: overrides.service_period_end ?? null,
		version: overrides.version ?? 1,
		created_by: overrides.created_by ?? "user-1",
		updated_by: overrides.updated_by ?? null,
		created_at: overrides.created_at ?? now,
		updated_at: overrides.updated_at ?? now,
	};
}

export function buildRosterRow(
	overrides: Partial<PayrollRunEmployeeResponse> & {
		employee_id: string;
		employee_number: string;
	},
): PayrollRunEmployeeResponse {
	return {
		employee_id: overrides.employee_id,
		employee_number: overrides.employee_number,
		employee_name: overrides.employee_name ?? `Employee ${overrides.employee_number}`,
		sevarth_id: overrides.sevarth_id ?? null,
		retirement_regime: overrides.retirement_regime ?? "nps",
		basic_pay: overrides.basic_pay ?? "50000.00",
		selected: overrides.selected ?? true,
		eligible: overrides.eligible ?? true,
		ineligible_reason:
			overrides.ineligible_reason ?? (overrides.eligible === false ? "no_active_profile" : null),
		payable_days: overrides.payable_days ?? "31.00",
		da_percent: overrides.da_percent ?? null,
		da_difference: overrides.da_difference ?? null,
		hra_percent: overrides.hra_percent ?? null,
		transport_amount: overrides.transport_amount ?? null,
	};
}

export function buildCurrentVersion(
	overrides: Partial<PayrollRunCalculateResult> = {},
): components["schemas"]["CurrentVersion"] {
	return {
		id: overrides.version_id ?? "ver-1",
		version_number: overrides.version_number ?? 1,
		content_hash: overrides.content_hash ?? "hash-abc123",
		engine_version: overrides.engine_version ?? "engine-1.0.0",
		calculated_at: "2026-07-18T12:00:00Z",
		totals: { ...DEFAULT_TOTALS, ...(overrides.totals ?? {}) } as { [key: string]: string },
	};
}

export function buildRunResults(overrides: Partial<PayrollRunResults> = {}): PayrollRunResults {
	return {
		version: overrides.version ?? buildCurrentVersion(),
		totals: overrides.totals ?? ({ ...DEFAULT_TOTALS } as { [key: string]: string }),
		employees: overrides.employees ?? [
			{
				employee_id: "emp-1",
				employee_number: "E-001",
				earnings_total: "60000.00",
				employer_contribution_total: "7000.00",
				gross_total: "67000.00",
				deductions_total: "8000.00",
				net_payable: "59000.00",
				offbill_employer_remittance: "0.00",
				disbursement: "59000.00",
			},
			{
				employee_id: "emp-2",
				employee_number: "E-002",
				earnings_total: "40000.00",
				employer_contribution_total: "5000.00",
				gross_total: "45000.00",
				deductions_total: "5000.00",
				net_payable: "40000.00",
				offbill_employer_remittance: "0.00",
				disbursement: "40000.00",
			},
		],
	};
}

export function createPayRunHandlers(options: PayRunHandlersOptions = {}) {
	const periods = new Map<string, PayrollPeriodResponse>();
	const runs = new Map<string, PayrollRunListItem>();
	const details = new Map<string, PayrollRunDetail>();
	const inputs = new Map<string, PayrollRunInputResponse[]>();
	const results = new Map<string, PayrollRunResults>();
	const rosters = new Map<string, PayrollRunEmployeeResponse[]>();
	const rosterHistory = new Map<string, PayrollRunRosterHistoryResponse[]>();

	const seedPeriods = options.periods ?? [
		buildPeriod({ id: "period-1", period_year: 2026, period_month: 7 }),
		buildPeriod({ id: "period-2", period_year: 2026, period_month: 6 }),
	];

	for (const period of seedPeriods) {
		periods.set(period.id, period);
	}

	const seedRuns = options.runs ?? [
		buildRun({
			id: "run-1",
			period_id: "period-1",
			period_year: 2026,
			period_month: 7,
			status: "draft",
		}),
		buildRun({
			id: "run-2",
			period_id: "period-2",
			period_year: 2026,
			period_month: 6,
			status: "calculated",
		}),
	];

	for (const run of seedRuns) {
		runs.set(run.id, run);
		const detail =
			options.details?.[run.id] ??
			buildRunDetail({
				id: run.id,
				period_id: run.period_id,
				period_year: run.period_year,
				period_month: run.period_month,
				status: run.status,
				lock_version: run.lock_version,
				current_version: null,
			});
		details.set(run.id, detail);
		inputs.set(run.id, options.inputs?.[run.id] ?? []);
		rosters.set(
			run.id,
			options.rosters?.[run.id] ?? [
				buildRosterRow({ employee_id: "emp-1", employee_number: "E-001" }),
				buildRosterRow({ employee_id: "emp-2", employee_number: "E-002" }),
			],
		);
		rosterHistory.set(run.id, options.rosterHistory?.[run.id] ?? []);
		if (options.results?.[run.id]) {
			results.set(run.id, options.results[run.id]);
		} else if (detail.current_version) {
			results.set(
				run.id,
				buildRunResults({
					version: detail.current_version,
					totals: detail.current_version.totals,
				}),
			);
		}
	}

	if (options.details) {
		for (const [runId, detail] of Object.entries(options.details)) {
			details.set(runId, detail);
			if (!runs.has(runId)) {
				runs.set(
					runId,
					buildRun({
						id: detail.id,
						period_id: detail.period_id,
						period_year: detail.period_year,
						period_month: detail.period_month,
						status: detail.status,
						lock_version: detail.lock_version,
					}),
				);
			}
			if (!inputs.has(runId)) {
				inputs.set(runId, options.inputs?.[runId] ?? []);
			}
			if (!rosterHistory.has(runId)) {
				rosterHistory.set(runId, options.rosterHistory?.[runId] ?? []);
			}
		}
	}

	if (options.inputs) {
		for (const [runId, list] of Object.entries(options.inputs)) {
			inputs.set(runId, list);
		}
	}

	if (options.results) {
		for (const [runId, value] of Object.entries(options.results)) {
			results.set(runId, value);
		}
	}

	if (options.rosters) {
		for (const [runId, value] of Object.entries(options.rosters)) {
			rosters.set(runId, value);
		}
	}

	const handlers = [
		http.get("/api/payroll-periods", () => {
			const items = Array.from(periods.values()).sort((a, b) => {
				if (a.period_year !== b.period_year) return b.period_year - a.period_year;
				return b.period_month - a.period_month;
			});
			return HttpResponse.json(items);
		}),

		http.post("/api/payroll-periods", async ({ request }) => {
			if (options.createPeriodError) {
				return HttpResponse.json(options.createPeriodError.body, {
					status: options.createPeriodError.status,
				});
			}
			const body = (await request.json()) as PayrollPeriodCreate;
			options.onCreatePeriod?.(body);
			const exists = Array.from(periods.values()).some(
				(period) =>
					period.period_year === body.period_year && period.period_month === body.period_month,
			);
			if (exists) {
				return HttpResponse.json(
					{ detail: "Payroll period already exists for this month", error: "ConflictError" },
					{ status: 409 },
				);
			}
			const id = `period-new-${periods.size + 1}`;
			const now = "2026-07-18T12:00:00Z";
			const created = buildPeriod({
				id,
				period_year: body.period_year,
				period_month: body.period_month,
				created_at: now,
				updated_at: now,
			});
			periods.set(id, created);
			return HttpResponse.json(created, { status: 201 });
		}),

		http.get("/api/payroll-runs", ({ request }) => {
			const url = new URL(request.url);
			const periodId = url.searchParams.get("period_id");
			const status = url.searchParams.get("status");
			let items = Array.from(runs.values());
			if (periodId) items = items.filter((run) => run.period_id === periodId);
			if (status) items = items.filter((run) => run.status === status);
			items.sort((a, b) => b.created_at.localeCompare(a.created_at));
			return HttpResponse.json(items);
		}),

		http.post("/api/payroll-runs", async ({ request }) => {
			if (options.createRunError) {
				return HttpResponse.json(options.createRunError.body, {
					status: options.createRunError.status,
				});
			}
			const body = (await request.json()) as PayrollRunCreate;
			options.onCreateRun?.(body);
			const period = periods.get(body.period_id);
			if (!period) {
				return HttpResponse.json(
					{ detail: "Period not found", error: "NotFound" },
					{ status: 404 },
				);
			}
			const id = `run-new-${runs.size + 1}`;
			const now = "2026-07-18T12:00:00Z";
			const created = buildRun({
				id,
				period_id: period.id,
				period_year: period.period_year,
				period_month: period.period_month,
				status: "draft",
				created_at: now,
				updated_at: now,
			});
			runs.set(id, created);
			details.set(
				id,
				buildRunDetail({
					id,
					period_id: period.id,
					period_year: period.period_year,
					period_month: period.period_month,
					status: "draft",
					roster_initialized: false,
					created_at: now,
					updated_at: now,
				}),
			);
			inputs.set(id, []);
			rosters.set(id, [
				buildRosterRow({ employee_id: "emp-1", employee_number: "E-001", selected: false }),
				buildRosterRow({ employee_id: "emp-2", employee_number: "E-002", selected: false }),
			]);
			rosterHistory.set(id, []);
			return HttpResponse.json(created, { status: 201 });
		}),

		http.get("/api/payroll-runs/:runId/roster", ({ params }) => {
			const runId = String(params.runId);
			if (!details.has(runId)) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			return HttpResponse.json(rosters.get(runId) ?? []);
		}),

		http.get("/api/payroll-runs/:runId/roster-history", ({ params }) => {
			const runId = String(params.runId);
			if (!details.has(runId)) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			return HttpResponse.json(rosterHistory.get(runId) ?? []);
		}),

		http.put("/api/payroll-runs/:runId/roster", async ({ params, request }) => {
			const runId = String(params.runId);
			const detail = details.get(runId);
			if (!detail) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			const body = (await request.json()) as PayrollRunRosterUpdate;
			options.onReplaceRoster?.(runId, body);
			const selectedById = new Map(
				body.employees.map((employee) => [employee.employee_id, employee]),
			);
			const next = (rosters.get(runId) ?? []).map((row) => {
				const selected = selectedById.get(row.employee_id);
				return selected
					? {
							...row,
							selected: true,
							payable_days: String(selected.payable_days),
							da_percent: selected.da_percent != null ? String(selected.da_percent) : null,
							da_difference: selected.da_difference != null ? String(selected.da_difference) : null,
							hra_percent: selected.hra_percent != null ? String(selected.hra_percent) : null,
							transport_amount:
								selected.transport_amount != null ? String(selected.transport_amount) : null,
						}
					: { ...row, selected: false };
			});
			rosters.set(runId, next);
			rosterHistory.set(runId, [
				{
					id: `history-${runId}-${(rosterHistory.get(runId)?.length ?? 0) + 1}`,
					action: detail.roster_initialized ? "Updated roster" : "Created roster",
					changed_employees: body.employees.length,
					selected_employees: body.employees.length,
					changed_fields: detail.roster_initialized ? ["Paid Days"] : ["Employees"],
					actor_name: "Dev Test User",
					created_at: "2026-07-18T12:30:00Z",
				},
				...(rosterHistory.get(runId) ?? []),
			]);
			details.set(runId, { ...detail, roster_initialized: true });
			return HttpResponse.json(next);
		}),

		http.get("/api/payroll-runs/:runId", ({ params }) => {
			const runId = String(params.runId);
			const detail = details.get(runId);
			if (!detail) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			return HttpResponse.json(detail);
		}),

		http.get("/api/payroll-runs/:runId/results", ({ params }) => {
			const runId = String(params.runId);
			const result = results.get(runId);
			if (!result) {
				return HttpResponse.json(
					{ detail: "Payroll run has no calculated version", error: "ConflictError" },
					{ status: 409 },
				);
			}
			return HttpResponse.json(result);
		}),

		http.post("/api/payroll-runs/:runId/calculate", ({ params }) => {
			const runId = String(params.runId);
			if (options.calculateError) {
				return HttpResponse.json(options.calculateError.body, {
					status: options.calculateError.status,
				});
			}
			const detail = details.get(runId);
			const run = runs.get(runId);
			if (!detail || !run) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			options.onCalculate?.(runId);

			const result: PayrollRunCalculateResult = {
				run_id: runId,
				version_id: options.calculateResult?.version_id ?? `ver-${runId}-2`,
				version_number: options.calculateResult?.version_number ?? 2,
				content_hash: options.calculateResult?.content_hash ?? "hash-calc-success",
				engine_version: options.calculateResult?.engine_version ?? "engine-1.0.0",
				totals: options.calculateResult?.totals ?? DEFAULT_TOTALS,
			};

			const nextDetail: PayrollRunDetail = {
				...detail,
				status: "calculated",
				lock_version: detail.lock_version + 1,
				current_version: buildCurrentVersion(result),
				updated_at: "2026-07-18T13:00:00Z",
			};
			details.set(runId, nextDetail);
			runs.set(runId, {
				...run,
				status: "calculated",
				lock_version: run.lock_version + 1,
				updated_at: nextDetail.updated_at,
			});
			results.set(
				runId,
				buildRunResults({
					version: nextDetail.current_version ?? buildCurrentVersion(result),
					totals: result.totals as { [key: string]: string },
				}),
			);

			return HttpResponse.json(result);
		}),

		http.get("/api/payroll-runs/:runId/inputs", ({ params }) => {
			const runId = String(params.runId);
			if (!details.has(runId)) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			return HttpResponse.json(inputs.get(runId) ?? []);
		}),

		http.put(
			"/api/payroll-runs/:runId/inputs/:employeeId/:componentCode",
			async ({ params, request }) => {
				const runId = String(params.runId);
				const employeeId = String(params.employeeId);
				const componentCode = decodeURIComponent(String(params.componentCode));
				const detail = details.get(runId);
				if (!detail) {
					return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
				}
				if (detail.status !== "draft") {
					return HttpResponse.json(
						{ detail: "Inputs can only be edited in draft status", error: "ConflictError" },
						{ status: 409 },
					);
				}
				const body = (await request.json()) as PayrollRunInputUpsert;
				options.onUpsertInput?.(runId, employeeId, componentCode, body);

				const list = inputs.get(runId) ?? [];
				const existingIndex = list.findIndex(
					(item) => item.employee_id === employeeId && item.component_code === componentCode,
				);
				const now = "2026-07-18T12:30:00Z";
				const next: PayrollRunInputResponse =
					existingIndex >= 0
						? {
								...list[existingIndex],
								input_kind: body.input_kind,
								amount: body.amount != null ? String(body.amount) : null,
								rate: body.rate != null ? String(body.rate) : null,
								reason: body.reason,
								service_period_start: body.service_period_start ?? null,
								service_period_end: body.service_period_end ?? null,
								version: list[existingIndex].version + 1,
								updated_at: now,
								updated_by: "user-1",
							}
						: buildRunInput({
								id: `input-new-${list.length + 1}`,
								run_id: runId,
								employee_id: employeeId,
								component_code: componentCode,
								input_kind: body.input_kind,
								amount: body.amount != null ? String(body.amount) : null,
								rate: body.rate != null ? String(body.rate) : null,
								reason: body.reason,
								service_period_start: body.service_period_start ?? null,
								service_period_end: body.service_period_end ?? null,
								created_at: now,
								updated_at: now,
							});

				if (existingIndex >= 0) {
					list[existingIndex] = next;
				} else {
					list.push(next);
				}
				inputs.set(runId, list);
				return HttpResponse.json(next);
			},
		),

		http.delete("/api/payroll-runs/:runId/inputs/:inputId", ({ params }) => {
			const runId = String(params.runId);
			const inputId = String(params.inputId);
			const detail = details.get(runId);
			if (!detail) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			if (detail.status !== "draft") {
				return HttpResponse.json(
					{ detail: "Inputs can only be edited in draft status", error: "ConflictError" },
					{ status: 409 },
				);
			}
			options.onDeleteInput?.(runId, inputId);
			const list = inputs.get(runId) ?? [];
			const next = list.filter((item) => item.id !== inputId);
			if (next.length === list.length) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			inputs.set(runId, next);
			return new HttpResponse(null, { status: 204 });
		}),
	];

	return { handlers, periods, runs, details, inputs, results };
}
