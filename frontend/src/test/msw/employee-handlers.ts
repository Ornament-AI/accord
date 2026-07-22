import { HttpResponse, http } from "msw";

import type {
	BankVersionResponse,
	CreateEmployeeRequest,
	EmployeeDetail,
	EmployeeSummary,
	PaginatedEmployeeSummary,
	ProfileVersionResponse,
} from "@/lib/api/employees";

type EmployeeRecord = {
	detail: EmployeeDetail;
	versions: {
		profile: ProfileVersionResponse[];
		posting: NonNullable<EmployeeDetail["posting"]>[];
		pay: NonNullable<EmployeeDetail["pay"]>[];
		bank: NonNullable<EmployeeDetail["bank"]>[];
	};
};

export type EmployeeHandlersOptions = {
	employees?: EmployeeSummary[];
	details?: Record<string, EmployeeDetail>;
	/** When set, POST /api/employees returns this status/body (e.g. 409). */
	createError?: { status: number; body: Record<string, unknown> };
	/** When set, POST .../versions/{kind} returns this status/body. */
	versionError?: { status: number; body: Record<string, unknown> };
	onCreate?: (body: CreateEmployeeRequest) => void;
	onCreateVersion?: (employeeId: string, kind: string, body: Record<string, unknown>) => void;
	pageSize?: number;
};

function maskPan(pan: string | null | undefined): string | null {
	if (pan == null) return null;
	if (pan.length > 4) return `••••${pan.slice(-4)}`;
	return "••••";
}

function maskAccount(account: string | null | undefined): string | null {
	if (account == null) return null;
	if (account.length > 4) return `••••${account.slice(-4)}`;
	return "••••";
}

function applyReveal(detail: EmployeeDetail, reveal: boolean): EmployeeDetail {
	if (reveal) return structuredClone(detail);
	const next = structuredClone(detail);
	if (next.profile) {
		next.profile = {
			...next.profile,
			pan: maskPan(next.profile.pan),
			pran: maskPan(next.profile.pran),
			gpf_account_number: maskPan(next.profile.gpf_account_number),
			epf_number: maskPan(next.profile.epf_number),
			pension_account: maskPan(next.profile.pension_account),
		};
	}
	if (next.bank) {
		next.bank = {
			...next.bank,
			account_number: maskAccount(next.bank.account_number) ?? next.bank.account_number,
		};
	}
	return next;
}

export function buildEmployeeDetail(
	overrides: Partial<EmployeeDetail> & { id: string; employee_number: string },
): EmployeeDetail {
	const now = "2026-01-15T10:00:00Z";
	const profile: ProfileVersionResponse = {
		id: `prof-${overrides.id}`,
		effective_from: "2026-01-01",
		effective_to: null,
		name: "Alice Example",
		sevarth_id: "SEV-001",
		pan: "ABCDE1234F",
		date_of_birth: "1990-01-15",
		date_of_joining: "2015-06-01",
		retirement_regime: "gpf",
		gpf_jurisdiction: "mumbai",
		pran: "123456789012",
		gpf_account_number: "GPF998877",
		epf_number: null,
		pension_account: null,
		created_at: now,
		created_by: "user-1",
		change_reason: null,
		...overrides.profile,
		payroll_export_remark: overrides.profile?.payroll_export_remark ?? null,
	};

	return {
		id: overrides.id,
		employee_number: overrides.employee_number,
		organization_id: overrides.organization_id ?? "org-acme",
		created_at: overrides.created_at ?? now,
		updated_at: overrides.updated_at ?? now,
		as_of: overrides.as_of ?? "2026-07-18",
		profile: overrides.profile === null ? null : profile,
		posting: overrides.posting ?? null,
		pay: overrides.pay ?? null,
		bank:
			overrides.bank === undefined
				? {
						id: `bank-${overrides.id}`,
						effective_from: "2026-01-01",
						effective_to: null,
						account_number: "123456789012",
						ifsc: "SBIN0001234",
						bank_name: "SBI",
						branch: "Main",
						is_primary_salary: true,
						created_at: now,
						created_by: "user-1",
						change_reason: null,
					}
				: overrides.bank,
	};
}

export function createEmployeeHandlers(options: EmployeeHandlersOptions = {}) {
	const pageSize = options.pageSize ?? 20;
	const store = new Map<string, EmployeeRecord>();

	const seedSummaries =
		options.employees ??
		Array.from({ length: 25 }, (_, index) => ({
			id: `emp-${index + 1}`,
			employee_number: `E-${String(index + 1).padStart(3, "0")}`,
			name: index === 0 ? "Alice Example" : `Employee ${index + 1}`,
			sevarth_id: `SEV-${String(index + 1).padStart(3, "0")}`,
			retirement_regime: index % 2 === 0 ? "gpf" : "nps",
		}));

	for (const summary of seedSummaries) {
		const detail =
			options.details?.[summary.id] ??
			buildEmployeeDetail({
				id: summary.id,
				employee_number: summary.employee_number,
				profile: {
					id: `prof-${summary.id}`,
					effective_from: "2026-01-01",
					effective_to: null,
					name: summary.name ?? "Unknown",
					sevarth_id: summary.sevarth_id ?? "SEV",
					pan: "ABCDE1234F",
					date_of_birth: "1990-01-15",
					date_of_joining: "2015-06-01",
					retirement_regime: summary.retirement_regime ?? "nps",
					gpf_jurisdiction: summary.retirement_regime === "gpf" ? "mumbai" : null,
					pran: null,
					gpf_account_number: null,
					epf_number: null,
					pension_account: null,
					payroll_export_remark: null,
					created_at: "2026-01-15T10:00:00Z",
					created_by: "user-1",
					change_reason: null,
				},
			});
		store.set(summary.id, {
			detail,
			versions: {
				profile: detail.profile ? [detail.profile] : [],
				posting: detail.posting ? [detail.posting] : [],
				pay: detail.pay ? [detail.pay] : [],
				bank: detail.bank ? [detail.bank] : [],
			},
		});
	}

	const handlers = [
		http.get("/api/employees", ({ request }) => {
			const url = new URL(request.url);
			const search = (url.searchParams.get("search") ?? "").trim().toLowerCase();
			const page = Number(url.searchParams.get("page") ?? "1");
			const size = Number(url.searchParams.get("size") ?? String(pageSize));

			let items = Array.from(store.values()).map((record) => ({
				id: record.detail.id,
				employee_number: record.detail.employee_number,
				name: record.detail.profile?.name ?? null,
				sevarth_id: record.detail.profile?.sevarth_id ?? null,
				retirement_regime: record.detail.profile?.retirement_regime ?? null,
			}));

			if (search) {
				items = items.filter(
					(item) =>
						item.employee_number.toLowerCase().includes(search) ||
						(item.name?.toLowerCase().includes(search) ?? false) ||
						(item.sevarth_id?.toLowerCase().includes(search) ?? false),
				);
			}

			items.sort((a, b) => a.employee_number.localeCompare(b.employee_number));
			const total = items.length;
			const totalPages = Math.max(1, Math.ceil(total / size));
			const start = (page - 1) * size;
			const pageItems = items.slice(start, start + size);

			const body: PaginatedEmployeeSummary = {
				items: pageItems,
				total,
				page,
				page_size: size,
				total_pages: totalPages,
			};
			return HttpResponse.json(body);
		}),

		http.get("/api/employees/:employeeId", ({ params, request }) => {
			const employeeId = String(params.employeeId);
			const record = store.get(employeeId);
			if (!record) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			const url = new URL(request.url);
			const reveal = url.searchParams.get("reveal") === "true";
			const asOf = url.searchParams.get("as_of") ?? record.detail.as_of;
			return HttpResponse.json(applyReveal({ ...record.detail, as_of: asOf }, reveal));
		}),

		http.post("/api/employees", async ({ request }) => {
			if (options.createError) {
				return HttpResponse.json(options.createError.body, {
					status: options.createError.status,
				});
			}
			const body = (await request.json()) as CreateEmployeeRequest;
			options.onCreate?.(body);
			const exists = Array.from(store.values()).some(
				(record) => record.detail.employee_number === body.employee_number,
			);
			if (exists) {
				return HttpResponse.json(
					{ detail: "Employee number already exists", error: "ConflictError" },
					{ status: 409 },
				);
			}
			const id = `emp-new-${store.size + 1}`;
			const detail = buildEmployeeDetail({
				id,
				employee_number: body.employee_number,
				profile: {
					id: `prof-${id}`,
					effective_from: body.effective_from,
					effective_to: null,
					name: body.profile.name,
					sevarth_id: body.profile.sevarth_id ?? null,
					pan: body.profile.pan ?? null,
					date_of_birth: body.profile.date_of_birth ?? null,
					date_of_joining: body.profile.date_of_joining ?? null,
					retirement_regime: body.profile.retirement_regime,
					gpf_jurisdiction: body.profile.gpf_jurisdiction ?? null,
					pran: body.profile.pran ?? null,
					gpf_account_number: body.profile.gpf_account_number ?? null,
					epf_number: body.profile.epf_number ?? null,
					pension_account: body.profile.pension_account ?? null,
					payroll_export_remark: body.profile.payroll_export_remark ?? null,
					created_at: "2026-01-15T10:00:00Z",
					created_by: "user-1",
					change_reason: null,
				},
			});
			store.set(id, {
				detail,
				versions: {
					profile: detail.profile ? [detail.profile] : [],
					posting: [],
					pay: [],
					bank: detail.bank ? [detail.bank] : [],
				},
			});
			return HttpResponse.json(applyReveal(detail, false), { status: 201 });
		}),

		http.get("/api/employees/:employeeId/versions/:kind", ({ params, request }) => {
			const employeeId = String(params.employeeId);
			const kind = String(params.kind) as keyof EmployeeRecord["versions"];
			const record = store.get(employeeId);
			if (!record) {
				return HttpResponse.json({ detail: "Not found" }, { status: 404 });
			}
			const url = new URL(request.url);
			const reveal = url.searchParams.get("reveal") === "true";
			if (kind === "profile") {
				const versions = record.versions.profile;
				if (!reveal) {
					return HttpResponse.json(
						versions.map((version) => ({
							...version,
							pan: maskPan(version.pan),
							pran: maskPan(version.pran),
							gpf_account_number: maskPan(version.gpf_account_number),
							epf_number: maskPan(version.epf_number),
							pension_account: maskPan(version.pension_account),
						})),
					);
				}
				return HttpResponse.json(versions);
			}
			if (kind === "bank") {
				const versions: BankVersionResponse[] = record.versions.bank;
				if (!reveal) {
					return HttpResponse.json(
						versions.map((version) => ({
							...version,
							account_number: maskAccount(version.account_number) ?? version.account_number,
						})),
					);
				}
				return HttpResponse.json(versions);
			}
			return HttpResponse.json(record.versions[kind] ?? []);
		}),

		http.post("/api/employees/:employeeId/versions/:kind", async ({ params, request }) => {
			if (options.versionError) {
				return HttpResponse.json(options.versionError.body, {
					status: options.versionError.status,
				});
			}
			const employeeId = String(params.employeeId);
			const kind = String(params.kind);
			const body = (await request.json()) as Record<string, unknown>;
			options.onCreateVersion?.(employeeId, kind, body);
			const record = store.get(employeeId);
			if (!record) {
				return HttpResponse.json({ detail: "Not found" }, { status: 404 });
			}
			return HttpResponse.json({ id: "version-new" }, { status: 201 });
		}),
	];

	return { handlers, store };
}
