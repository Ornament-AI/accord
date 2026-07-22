import { HttpResponse, http } from "msw";

import type {
	ComponentRateVersionCreate,
	ComponentRateVersionResponse,
	PayComponentCreate,
	PayComponentResponse,
	PayComponentUpdate,
	PayrollExportProfile,
	PayrollExportProfileResponse,
} from "@/lib/api/pay-setup";

export type PayComponentHandlersOptions = {
	components?: PayComponentResponse[];
	rateVersions?: Record<string, ComponentRateVersionResponse[]>;
	/** When set, POST /api/pay-components returns this status/body (e.g. 409). */
	createError?: { status: number; body: Record<string, unknown> };
	/** When set, POST .../rate-versions returns this status/body. */
	rateVersionError?: { status: number; body: Record<string, unknown> };
	/** Collect PATCH bodies for assertions. */
	onPatch?: (componentId: string, body: PayComponentUpdate) => void;
	/** Collect create bodies for assertions. */
	onCreate?: (body: PayComponentCreate) => void;
	/** Collect rate-version create bodies for assertions. */
	onCreateRateVersion?: (componentId: string, body: ComponentRateVersionCreate) => void;
	reportProfile?: PayrollExportProfile;
	onUpdateReportProfile?: (body: PayrollExportProfile) => void;
};

export function buildPayComponent(
	overrides: Partial<PayComponentResponse> & { id: string; code: string },
): PayComponentResponse {
	const now = "2026-01-15T10:00:00Z";
	return {
		id: overrides.id,
		code: overrides.code,
		name: overrides.name ?? overrides.code,
		classification: overrides.classification ?? "earning",
		display_order: overrides.display_order ?? 0,
		employer_transfer: overrides.employer_transfer ?? false,
		transfer_of: overrides.transfer_of ?? null,
		is_active: overrides.is_active ?? true,
		is_standard: overrides.is_standard ?? false,
		schedule_kind: overrides.schedule_kind ?? null,
		schedule_title: overrides.schedule_title ?? null,
		schedule_account_head: overrides.schedule_account_head ?? null,
		register_column: overrides.register_column ?? null,
		created_at: overrides.created_at ?? now,
		updated_at: overrides.updated_at ?? now,
	};
}

export function buildRateVersion(
	overrides: Partial<ComponentRateVersionResponse> & { id: string },
): ComponentRateVersionResponse {
	return {
		id: overrides.id,
		effective_from: overrides.effective_from ?? "2026-01-01",
		effective_to: overrides.effective_to ?? null,
		calc_kind: overrides.calc_kind ?? "fixed_recurring_amount",
		rounding_rule: overrides.rounding_rule ?? "ROUND_HALF_UP_RUPEE",
		amount: overrides.amount ?? "1000.00",
		rate: overrides.rate ?? null,
		basis: overrides.basis ?? null,
		change_reason: overrides.change_reason ?? null,
		created_at: overrides.created_at ?? "2026-01-15T10:00:00Z",
		created_by: overrides.created_by ?? "user-1",
	};
}

export function createPayComponentHandlers(options: PayComponentHandlersOptions = {}) {
	const store = new Map<string, PayComponentResponse>();
	const rateVersions = new Map<string, ComponentRateVersionResponse[]>();
	let reportProfile: PayrollExportProfile = options.reportProfile ?? {};

	const seed = options.components ?? [
		buildPayComponent({
			id: "pc-1",
			code: "BASIC",
			name: "Basic Pay",
			classification: "earning",
			display_order: 1,
		}),
		buildPayComponent({
			id: "pc-2",
			code: "HRA",
			name: "House Rent Allowance",
			classification: "earning",
			display_order: 2,
		}),
		buildPayComponent({
			id: "pc-3",
			code: "GPF",
			name: "GPF Deduction",
			classification: "treasury_deduction",
			display_order: 10,
			is_active: true,
		}),
	];

	for (const component of seed) {
		store.set(component.id, component);
		rateVersions.set(
			component.id,
			options.rateVersions?.[component.id] ??
				(component.id === "pc-1"
					? [
							buildRateVersion({
								id: "rv-1",
								effective_from: "2026-01-01",
								effective_to: null,
								calc_kind: "fixed_recurring_amount",
								amount: "50000.00",
							}),
						]
					: []),
		);
	}

	const handlers = [
		http.get("/api/report-profile", () => {
			const response: PayrollExportProfileResponse = {
				value: reportProfile,
				updated_at: "2026-07-18T12:00:00Z",
			};
			return HttpResponse.json(response);
		}),

		http.put("/api/report-profile", async ({ request }) => {
			const body = (await request.json()) as PayrollExportProfile;
			options.onUpdateReportProfile?.(body);
			reportProfile = body;
			const response: PayrollExportProfileResponse = {
				value: reportProfile,
				updated_at: "2026-07-18T12:30:00Z",
			};
			return HttpResponse.json(response);
		}),

		http.get("/api/pay-components", () => {
			const items = Array.from(store.values()).sort(
				(a, b) => a.display_order - b.display_order || a.code.localeCompare(b.code),
			);
			return HttpResponse.json(items);
		}),

		http.post("/api/pay-components", async ({ request }) => {
			if (options.createError) {
				return HttpResponse.json(options.createError.body, {
					status: options.createError.status,
				});
			}
			const body = (await request.json()) as PayComponentCreate;
			options.onCreate?.(body);
			const exists = Array.from(store.values()).some(
				(component) => component.code.toLowerCase() === body.code.trim().toLowerCase(),
			);
			if (exists) {
				return HttpResponse.json(
					{ detail: "Pay component code already exists", error: "ConflictError" },
					{ status: 409 },
				);
			}
			const id = `pc-new-${store.size + 1}`;
			const now = "2026-07-18T12:00:00Z";
			const created = buildPayComponent({
				id,
				code: body.code.trim(),
				name: body.name.trim(),
				classification: body.classification,
				display_order: body.display_order ?? 0,
				employer_transfer: body.employer_transfer,
				transfer_of: body.transfer_of ?? null,
				register_column: body.register_column ?? null,
				created_at: now,
				updated_at: now,
			});
			store.set(id, created);
			rateVersions.set(id, []);
			return HttpResponse.json(created, { status: 201 });
		}),

		http.patch("/api/pay-components/:componentId", async ({ params, request }) => {
			const componentId = String(params.componentId);
			const existing = store.get(componentId);
			if (!existing) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			const body = (await request.json()) as Record<string, unknown>;
			if ("code" in body || "classification" in body) {
				return HttpResponse.json(
					{
						detail: "code and classification are immutable after creation.",
						error: "ConflictError",
					},
					{ status: 409 },
				);
			}
			const update = body as PayComponentUpdate;
			options.onPatch?.(componentId, update);
			const next: PayComponentResponse = {
				...existing,
				name: update.name ?? existing.name,
				display_order: update.display_order ?? existing.display_order,
				is_active: update.is_active ?? existing.is_active,
				employer_transfer: update.employer_transfer ?? existing.employer_transfer,
				transfer_of: update.transfer_of === undefined ? existing.transfer_of : update.transfer_of,
				register_column:
					update.register_column === undefined ? existing.register_column : update.register_column,
				updated_at: "2026-07-18T12:30:00Z",
			};
			store.set(componentId, next);
			return HttpResponse.json(next);
		}),

		http.get("/api/pay-components/:componentId/rate-versions", ({ params }) => {
			const componentId = String(params.componentId);
			if (!store.has(componentId)) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			return HttpResponse.json(rateVersions.get(componentId) ?? []);
		}),

		http.post("/api/pay-components/:componentId/rate-versions", async ({ params, request }) => {
			if (options.rateVersionError) {
				return HttpResponse.json(options.rateVersionError.body, {
					status: options.rateVersionError.status,
				});
			}
			const componentId = String(params.componentId);
			if (!store.has(componentId)) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			const body = (await request.json()) as ComponentRateVersionCreate;
			options.onCreateRateVersion?.(componentId, body);
			const created = buildRateVersion({
				id: `rv-new-${(rateVersions.get(componentId)?.length ?? 0) + 1}`,
				effective_from: body.effective_from,
				effective_to: null,
				calc_kind: body.calc_kind,
				rounding_rule: body.rounding_rule,
				amount: body.amount != null ? String(body.amount) : null,
				rate: body.rate != null ? String(body.rate) : null,
				basis: body.basis ?? null,
				change_reason: body.change_reason ?? null,
			});
			const list = rateVersions.get(componentId) ?? [];
			list.push(created);
			rateVersions.set(componentId, list);
			return HttpResponse.json(created, { status: 201 });
		}),
	];

	return { handlers, store, rateVersions };
}
