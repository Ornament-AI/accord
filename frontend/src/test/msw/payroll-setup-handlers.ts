import { HttpResponse, http } from "msw";

import type {
	AccommodationChargeVersionCreate,
	AccommodationCreate,
	AccommodationResponse,
	AccommodationUpdate,
	AdvanceCreate,
	AdvanceInstallmentVersionCreate,
	AdvanceResponse,
	RecurringInstructionCreate,
	RecurringInstructionResponse,
	RecurringInstructionVersionCreate,
} from "@/lib/api/employee-payroll-setup";

import { buildPayComponent, createPayComponentHandlers } from "@/test/msw/pay-component-handlers";

export type PayrollSetupHandlersOptions = {
	employeeId?: string;
	recurringInstructions?: RecurringInstructionResponse[];
	advances?: AdvanceResponse[];
	accommodation?: AccommodationResponse[];
	/** When set, POST recurring-instructions returns this status/body. */
	createInstructionError?: { status: number; body: Record<string, unknown> };
	/** When set, POST recurring-instructions/{id}/versions returns this status/body. */
	instructionVersionError?: { status: number; body: Record<string, unknown> };
	/** Collect version create bodies for assertions. */
	onCreateInstructionVersion?: (
		instructionId: string,
		body: RecurringInstructionVersionCreate,
	) => void;
	onCreateInstruction?: (body: RecurringInstructionCreate) => void;
	onCreateAdvance?: (body: AdvanceCreate) => void;
	onCreateAccommodation?: (body: AccommodationCreate) => void;
	onUpdateAccommodation?: (assignmentId: string, body: AccommodationUpdate) => void;
	onCreateAccommodationChargeVersion?: (
		assignmentId: string,
		body: AccommodationChargeVersionCreate,
	) => void;
};

export function buildRecurringInstruction(
	overrides: Partial<RecurringInstructionResponse> & { id: string; employee_id: string },
): RecurringInstructionResponse {
	const now = "2026-01-15T10:00:00Z";
	return {
		id: overrides.id,
		employee_id: overrides.employee_id,
		component_id: overrides.component_id ?? "pc-hra",
		amount: overrides.amount === undefined ? "2500.00" : overrides.amount,
		rate: overrides.rate === undefined ? null : overrides.rate,
		effective_from: overrides.effective_from ?? "2026-01-01",
		effective_to: overrides.effective_to === undefined ? null : overrides.effective_to,
		reason: overrides.reason ?? null,
		version_id: overrides.version_id ?? `riv-${overrides.id}`,
		created_at: overrides.created_at ?? now,
		updated_at: overrides.updated_at ?? now,
	};
}

export function buildAdvance(
	overrides: Partial<AdvanceResponse> & { id: string; employee_id: string },
): AdvanceResponse {
	const now = "2026-01-15T10:00:00Z";
	return {
		id: overrides.id,
		employee_id: overrides.employee_id,
		advance_type: overrides.advance_type ?? "hba",
		principal: overrides.principal ?? "100000.00",
		sanctioned_on: overrides.sanctioned_on ?? "2026-02-01",
		reference: overrides.reference === undefined ? "ADV-001" : overrides.reference,
		installment_amount:
			overrides.installment_amount === undefined ? "5000.00" : overrides.installment_amount,
		installments_recovered_opening:
			overrides.installments_recovered_opening === undefined
				? 2
				: overrides.installments_recovered_opening,
		installments_total:
			overrides.installments_total === undefined ? 20 : overrides.installments_total,
		effective_from: overrides.effective_from ?? "2026-02-01",
		effective_to: overrides.effective_to === undefined ? null : overrides.effective_to,
		version_id: overrides.version_id ?? `aiv-${overrides.id}`,
		created_at: overrides.created_at ?? now,
		updated_at: overrides.updated_at ?? now,
	};
}

export function buildAccommodation(
	overrides: Partial<AccommodationResponse> & { id: string; employee_id: string },
): AccommodationResponse {
	const now = "2026-01-15T10:00:00Z";
	return {
		id: overrides.id,
		employee_id: overrides.employee_id,
		quarters_location: overrides.quarters_location ?? "mumbai",
		quarters_identifier: overrides.quarters_identifier ?? "B-12",
		quarters_address: overrides.quarters_address ?? null,
		license_fee: overrides.license_fee === undefined ? "1200.00" : overrides.license_fee,
		house_rent: overrides.house_rent ?? null,
		service_charge: overrides.service_charge ?? null,
		parking_charge: overrides.parking_charge ?? null,
		additional_parking_charge: overrides.additional_parking_charge ?? null,
		informational_hra_foregone:
			overrides.informational_hra_foregone === undefined
				? "8500.00"
				: overrides.informational_hra_foregone,
		effective_from: overrides.effective_from ?? "2026-01-01",
		effective_to: overrides.effective_to === undefined ? null : overrides.effective_to,
		version_id: overrides.version_id ?? `acv-${overrides.id}`,
		created_at: overrides.created_at ?? now,
		updated_at: overrides.updated_at ?? now,
	};
}

export function createPayrollSetupHandlers(options: PayrollSetupHandlersOptions = {}) {
	const employeeId = options.employeeId ?? "emp-1";

	const recurringStore = new Map<string, RecurringInstructionResponse>();
	const advanceStore = new Map<string, AdvanceResponse>();
	const accommodationStore = new Map<string, AccommodationResponse>();

	const seedRecurring = options.recurringInstructions ?? [
		buildRecurringInstruction({
			id: "ri-1",
			employee_id: employeeId,
			component_id: "pc-hra",
			amount: "2500.00",
			effective_from: "2026-01-01",
		}),
	];
	for (const item of seedRecurring) {
		recurringStore.set(item.id, item);
	}

	const seedAdvances = options.advances ?? [
		buildAdvance({
			id: "adv-1",
			employee_id: employeeId,
			advance_type: "hba",
			principal: "100000.00",
			installment_amount: "5000.00",
			installments_recovered_opening: 2,
			installments_total: 20,
		}),
	];
	for (const item of seedAdvances) {
		advanceStore.set(item.id, item);
	}

	const seedAccommodation = options.accommodation ?? [
		buildAccommodation({
			id: "acc-1",
			employee_id: employeeId,
			quarters_location: "mumbai",
			quarters_identifier: "B-12",
			license_fee: "1200.00",
			informational_hra_foregone: "8500.00",
		}),
	];
	for (const item of seedAccommodation) {
		accommodationStore.set(item.id, item);
	}

	const { handlers: payComponentHandlers } = createPayComponentHandlers({
		components: [
			buildPayComponent({
				id: "pc-hra",
				code: "HRA",
				name: "House Rent Allowance",
				classification: "earning",
				display_order: 2,
			}),
			buildPayComponent({
				id: "pc-cca",
				code: "CCA",
				name: "City Compensatory Allowance",
				classification: "earning",
				display_order: 3,
			}),
		],
	});

	const handlers = [
		...payComponentHandlers,

		http.get("/api/employees/:employeeId/recurring-instructions", ({ params }) => {
			const items = Array.from(recurringStore.values()).filter(
				(item) => item.employee_id === params.employeeId,
			);
			return HttpResponse.json(items);
		}),

		http.post("/api/employees/:employeeId/recurring-instructions", async ({ params, request }) => {
			if (options.createInstructionError) {
				return HttpResponse.json(options.createInstructionError.body, {
					status: options.createInstructionError.status,
				});
			}
			const body = (await request.json()) as RecurringInstructionCreate;
			options.onCreateInstruction?.(body);
			const now = "2026-07-18T10:00:00Z";
			const created = buildRecurringInstruction({
				id: `ri-${recurringStore.size + 1}`,
				employee_id: String(params.employeeId),
				component_id: body.component_id,
				amount: body.amount == null ? null : String(body.amount),
				rate: body.rate == null ? null : String(body.rate),
				effective_from: body.effective_from,
				reason: body.reason ?? null,
				created_at: now,
				updated_at: now,
			});
			recurringStore.set(created.id, created);
			return HttpResponse.json(created, { status: 201 });
		}),

		http.post(
			"/api/recurring-instructions/:instructionId/versions",
			async ({ params, request }) => {
				if (options.instructionVersionError) {
					return HttpResponse.json(options.instructionVersionError.body, {
						status: options.instructionVersionError.status,
					});
				}
				const body = (await request.json()) as RecurringInstructionVersionCreate;
				const instructionId = String(params.instructionId);
				options.onCreateInstructionVersion?.(instructionId, body);

				const existing = recurringStore.get(instructionId);
				if (!existing) {
					return HttpResponse.json({ detail: "Not found" }, { status: 404 });
				}

				if (body.end_on) {
					const updated: RecurringInstructionResponse = {
						...existing,
						effective_to: body.end_on,
						updated_at: "2026-07-18T10:00:00Z",
					};
					recurringStore.set(instructionId, updated);
					return HttpResponse.json(
						{
							id: `riv-end-${instructionId}`,
							effective_from: existing.effective_from ?? body.end_on,
							effective_to: body.end_on,
							amount: existing.amount,
							rate: existing.rate,
							reason: existing.reason,
							change_reason: body.change_reason ?? null,
							created_at: "2026-07-18T10:00:00Z",
							created_by: "user-1",
						},
						{ status: 201 },
					);
				}

				const updated: RecurringInstructionResponse = {
					...existing,
					amount: body.amount == null ? existing.amount : String(body.amount),
					rate: body.rate == null ? existing.rate : String(body.rate),
					effective_from: body.effective_from ?? existing.effective_from,
					updated_at: "2026-07-18T10:00:00Z",
				};
				recurringStore.set(instructionId, updated);
				return HttpResponse.json(
					{
						id: `riv-${instructionId}-new`,
						effective_from: body.effective_from ?? existing.effective_from ?? "2026-01-01",
						effective_to: null,
						amount: updated.amount,
						rate: updated.rate,
						reason: existing.reason,
						change_reason: body.change_reason ?? null,
						created_at: "2026-07-18T10:00:00Z",
						created_by: "user-1",
					},
					{ status: 201 },
				);
			},
		),

		http.get("/api/employees/:employeeId/advances", ({ params }) => {
			const items = Array.from(advanceStore.values()).filter(
				(item) => item.employee_id === params.employeeId,
			);
			return HttpResponse.json(items);
		}),

		http.post("/api/employees/:employeeId/advances", async ({ params, request }) => {
			const body = (await request.json()) as AdvanceCreate;
			options.onCreateAdvance?.(body);
			const created = buildAdvance({
				id: `adv-${advanceStore.size + 1}`,
				employee_id: String(params.employeeId),
				advance_type: body.advance_type,
				principal: String(body.principal),
				sanctioned_on: body.sanctioned_on,
				reference: body.reference ?? null,
				installment_amount: String(body.installment.installment_amount),
				installments_recovered_opening: body.installment.installments_recovered_opening,
				installments_total: body.installment.installments_total,
				effective_from: body.installment.effective_from,
			});
			advanceStore.set(created.id, created);
			return HttpResponse.json(created, { status: 201 });
		}),

		http.post("/api/advances/:advanceId/installment-versions", async ({ params, request }) => {
			const body = (await request.json()) as AdvanceInstallmentVersionCreate;
			const advanceId = String(params.advanceId);
			const existing = advanceStore.get(advanceId);
			if (!existing) {
				return HttpResponse.json({ detail: "Not found" }, { status: 404 });
			}
			const updated: AdvanceResponse = {
				...existing,
				installment_amount: String(body.installment_amount),
				installments_recovered_opening: body.installments_recovered_opening,
				installments_total: body.installments_total,
				effective_from: body.effective_from,
				updated_at: "2026-07-18T10:00:00Z",
			};
			advanceStore.set(advanceId, updated);
			return HttpResponse.json(
				{
					id: `aiv-${advanceId}-new`,
					effective_from: body.effective_from,
					effective_to: null,
					installment_amount: String(body.installment_amount),
					installments_recovered_opening: body.installments_recovered_opening,
					installments_total: body.installments_total,
					change_reason: body.change_reason ?? null,
					created_at: "2026-07-18T10:00:00Z",
					created_by: "user-1",
				},
				{ status: 201 },
			);
		}),

		http.get("/api/employees/:employeeId/accommodation", ({ params }) => {
			const items = Array.from(accommodationStore.values()).filter(
				(item) => item.employee_id === params.employeeId,
			);
			return HttpResponse.json(items);
		}),

		http.post("/api/employees/:employeeId/accommodation", async ({ params, request }) => {
			const body = (await request.json()) as AccommodationCreate;
			options.onCreateAccommodation?.(body);
			const created = buildAccommodation({
				id: `acc-${accommodationStore.size + 1}`,
				employee_id: String(params.employeeId),
				quarters_location: body.quarters_location,
				quarters_identifier: body.quarters_identifier,
				quarters_address: body.quarters_address ?? null,
				license_fee: String(body.charge.license_fee),
				house_rent: body.charge.house_rent == null ? null : String(body.charge.house_rent),
				service_charge:
					body.charge.service_charge == null ? null : String(body.charge.service_charge),
				parking_charge:
					body.charge.parking_charge == null ? null : String(body.charge.parking_charge),
				additional_parking_charge:
					body.charge.additional_parking_charge == null
						? null
						: String(body.charge.additional_parking_charge),
				informational_hra_foregone:
					body.charge.informational_hra_foregone == null
						? null
						: String(body.charge.informational_hra_foregone),
				effective_from: body.charge.effective_from,
			});
			accommodationStore.set(created.id, created);
			return HttpResponse.json(created, { status: 201 });
		}),

		http.patch("/api/accommodation/:assignmentId", async ({ params, request }) => {
			const body = (await request.json()) as AccommodationUpdate;
			const assignmentId = String(params.assignmentId);
			options.onUpdateAccommodation?.(assignmentId, body);
			const existing = accommodationStore.get(assignmentId);
			if (!existing) {
				return HttpResponse.json({ detail: "Not found" }, { status: 404 });
			}
			const updated: AccommodationResponse = {
				...existing,
				quarters_identifier: body.quarters_identifier ?? existing.quarters_identifier,
				quarters_address:
					body.quarters_address === undefined ? existing.quarters_address : body.quarters_address,
				updated_at: "2026-07-18T10:00:00Z",
			};
			accommodationStore.set(assignmentId, updated);
			return HttpResponse.json(updated);
		}),

		http.post("/api/accommodation/:assignmentId/charge-versions", async ({ params, request }) => {
			const body = (await request.json()) as AccommodationChargeVersionCreate;
			const assignmentId = String(params.assignmentId);
			options.onCreateAccommodationChargeVersion?.(assignmentId, body);
			const existing = accommodationStore.get(assignmentId);
			if (!existing) {
				return HttpResponse.json({ detail: "Not found" }, { status: 404 });
			}
			const updated: AccommodationResponse = {
				...existing,
				license_fee: String(body.license_fee),
				house_rent: body.house_rent == null ? null : String(body.house_rent),
				service_charge: body.service_charge == null ? null : String(body.service_charge),
				parking_charge: body.parking_charge == null ? null : String(body.parking_charge),
				additional_parking_charge:
					body.additional_parking_charge == null ? null : String(body.additional_parking_charge),
				informational_hra_foregone:
					body.informational_hra_foregone == null
						? existing.informational_hra_foregone
						: String(body.informational_hra_foregone),
				effective_from: body.effective_from,
				updated_at: "2026-07-18T10:00:00Z",
			};
			accommodationStore.set(assignmentId, updated);
			return HttpResponse.json(
				{
					id: `acv-${assignmentId}-new`,
					effective_from: body.effective_from,
					effective_to: null,
					license_fee: String(body.license_fee),
					house_rent: body.house_rent == null ? null : String(body.house_rent),
					service_charge: body.service_charge == null ? null : String(body.service_charge),
					parking_charge: body.parking_charge == null ? null : String(body.parking_charge),
					additional_parking_charge:
						body.additional_parking_charge == null ? null : String(body.additional_parking_charge),
					informational_hra_foregone:
						body.informational_hra_foregone == null
							? null
							: String(body.informational_hra_foregone),
					change_reason: body.change_reason ?? null,
					created_at: "2026-07-18T10:00:00Z",
					created_by: "user-1",
				},
				{ status: 201 },
			);
		}),
	];

	return { handlers };
}
