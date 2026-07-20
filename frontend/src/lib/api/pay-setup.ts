import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJson } from "@/lib/api/http";
import { ApiError } from "@/lib/errors";
import type { components } from "@/types/api.generated";

export type PayComponentCreate = components["schemas"]["PayComponentCreate"];
export type PayComponentResponse = components["schemas"]["PayComponentResponse"];
export type ComponentRateVersionCreate = components["schemas"]["ComponentRateVersionCreate"];
export type ComponentRateVersionResponse = components["schemas"]["ComponentRateVersionResponse"];
export type CalcKind = components["schemas"]["CalcKind"];
export type Classification = components["schemas"]["Classification"];
export type RoundingRule = components["schemas"]["RoundingRule"];
export type ScheduleKind = components["schemas"]["ScheduleKind"];
export type PayrollExportProfile = components["schemas"]["PayrollExportProfile"];
export type PayrollExportProfileResponse = components["schemas"]["PayrollExportProfileResponse"];

export type PayComponentUpdate = {
	name?: string;
	display_order?: number;
	is_active?: boolean;
	employer_transfer?: boolean;
	transfer_of?: string | null;
	schedule_kind?: ScheduleKind | null;
	schedule_title?: string | null;
	schedule_account_head?: string | null;
};

export const CLASSIFICATIONS: Classification[] = [
	"earning",
	"employer_contribution",
	"ag_deduction",
	"treasury_deduction",
	"gross_adjustment",
	"external_recovery",
	"informational",
];

export const CALC_KINDS: CalcKind[] = [
	"fixed_recurring_amount",
	"direct_monthly_amount",
	"percentage_of_component_bases",
	"employer_employee_contribution",
	"loan_installment_recovery",
	"accommodation_charge",
	"one_time_adjustment",
];

export const ROUNDING_RULES: RoundingRule[] = [
	"ROUND_HALF_UP_RUPEE",
	"ROUND_HALF_UP_PAISE",
	"ROUND_DOWN_RUPEE",
];

const AMOUNT_CALC_KINDS: ReadonlySet<CalcKind> = new Set([
	"fixed_recurring_amount",
	"direct_monthly_amount",
	"loan_installment_recovery",
	"accommodation_charge",
	"one_time_adjustment",
]);

const RATE_CALC_KINDS: ReadonlySet<CalcKind> = new Set([
	"percentage_of_component_bases",
	"employer_employee_contribution",
]);

const BASIS_CALC_KINDS: ReadonlySet<CalcKind> = new Set([
	"percentage_of_component_bases",
	"employer_employee_contribution",
]);

export function calcKindUsesAmount(kind: CalcKind): boolean {
	return AMOUNT_CALC_KINDS.has(kind);
}

export function calcKindUsesRate(kind: CalcKind): boolean {
	return RATE_CALC_KINDS.has(kind);
}

export function calcKindUsesBasis(kind: CalcKind): boolean {
	return BASIS_CALC_KINDS.has(kind);
}

const CLASSIFICATION_LABELS: Record<Classification, string> = {
	earning: "Earning",
	employer_contribution: "Employer Contribution",
	ag_deduction: "AG Deduction",
	treasury_deduction: "Treasury Deduction",
	gross_adjustment: "Gross Adjustment",
	external_recovery: "External Recovery",
	informational: "Informational",
};

export function classificationLabel(value: string): string {
	if (value in CLASSIFICATION_LABELS) {
		return CLASSIFICATION_LABELS[value as Classification];
	}
	return value
		.split("_")
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

export function calcKindLabel(value: string): string {
	return value
		.split("_")
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

export function roundingRuleLabel(value: string): string {
	switch (value) {
		case "ROUND_HALF_UP_RUPEE":
			return "Round half up (rupee)";
		case "ROUND_HALF_UP_PAISE":
			return "Round half up (paise)";
		case "ROUND_DOWN_RUPEE":
			return "Round down (rupee)";
		default:
			return value;
	}
}

export const paySetupQueryKeys = {
	all: () => ["pay-setup"] as const,
	components: () => ["pay-setup", "components"] as const,
	component: (componentId: string) => ["pay-setup", "components", componentId] as const,
	rateVersions: (componentId: string) =>
		["pay-setup", "components", componentId, "rate-versions"] as const,
	reportProfile: () => ["pay-setup", "report-profile"] as const,
};

export function listPayComponents() {
	return fetchJson<PayComponentResponse[]>("/api/pay-components");
}

export function getPayrollExportProfile() {
	return fetchJson<PayrollExportProfileResponse>("/api/report-profile");
}

export function updatePayrollExportProfile(body: PayrollExportProfile) {
	return fetchJson<PayrollExportProfileResponse>("/api/report-profile", {
		method: "PUT",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

/** Resolve a single component from the list endpoint (OpenAPI has no GET-by-id). */
export async function getPayComponent(componentId: string): Promise<PayComponentResponse> {
	const components = await listPayComponents();
	const found = components.find((component) => component.id === componentId);
	if (!found) {
		throw new ApiError("Pay component not found", 404, {
			detail: "Pay component not found",
			code: "NotFound",
		});
	}
	return found;
}

export function createPayComponent(body: PayComponentCreate) {
	return fetchJson<PayComponentResponse>("/api/pay-components", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function updatePayComponent(componentId: string, body: PayComponentUpdate) {
	return fetchJson<PayComponentResponse>(`/api/pay-components/${componentId}`, {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function listComponentRateVersions(componentId: string) {
	return fetchJson<ComponentRateVersionResponse[]>(
		`/api/pay-components/${componentId}/rate-versions`,
	);
}

export function createComponentRateVersion(componentId: string, body: ComponentRateVersionCreate) {
	return fetchJson<ComponentRateVersionResponse>(
		`/api/pay-components/${componentId}/rate-versions`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(body),
		},
	);
}

export function usePayComponentsList() {
	return useQuery({
		queryKey: paySetupQueryKeys.components(),
		queryFn: listPayComponents,
	});
}

export function usePayrollExportProfile() {
	return useQuery({
		queryKey: paySetupQueryKeys.reportProfile(),
		queryFn: getPayrollExportProfile,
	});
}

export function useUpdatePayrollExportProfile() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: updatePayrollExportProfile,
		onSuccess: (data) => {
			queryClient.setQueryData(paySetupQueryKeys.reportProfile(), data);
		},
	});
}

export function usePayComponent(componentId: string | undefined) {
	return useQuery({
		queryKey: paySetupQueryKeys.component(componentId ?? ""),
		queryFn: () => getPayComponent(componentId!),
		enabled: Boolean(componentId),
	});
}

export function useComponentRateVersions(componentId: string | undefined) {
	return useQuery({
		queryKey: paySetupQueryKeys.rateVersions(componentId ?? ""),
		queryFn: () => listComponentRateVersions(componentId!),
		enabled: Boolean(componentId),
	});
}

export function useCreatePayComponent() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: createPayComponent,
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: paySetupQueryKeys.components() });
		},
	});
}

export function useUpdatePayComponent() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({ componentId, body }: { componentId: string; body: PayComponentUpdate }) =>
			updatePayComponent(componentId, body),
		onSuccess: (_data, variables) => {
			void queryClient.invalidateQueries({ queryKey: paySetupQueryKeys.components() });
			void queryClient.invalidateQueries({
				queryKey: paySetupQueryKeys.component(variables.componentId),
			});
		},
	});
}

export function useCreateComponentRateVersion(componentId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (body: ComponentRateVersionCreate) => createComponentRateVersion(componentId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({
				queryKey: paySetupQueryKeys.rateVersions(componentId),
			});
		},
	});
}

// --- Employee-scoped payroll setup (recurring instructions, advances, accommodation) ---

export type RecurringInstructionCreate = components["schemas"]["RecurringInstructionCreate"];
export type RecurringInstructionResponse = components["schemas"]["RecurringInstructionResponse"];
export type RecurringInstructionVersionCreate =
	components["schemas"]["RecurringInstructionVersionCreate"];
export type RecurringInstructionVersionResponse =
	components["schemas"]["RecurringInstructionVersionResponse"];

export type AdvanceCreate = components["schemas"]["AdvanceCreate"];
export type AdvanceResponse = components["schemas"]["AdvanceResponse"];
export type AdvanceInstallmentVersionCreate =
	components["schemas"]["AdvanceInstallmentVersionCreate"];
export type AdvanceInstallmentVersionResponse =
	components["schemas"]["AdvanceInstallmentVersionResponse"];
export type AdvanceType = components["schemas"]["AdvanceType"];

export type AccommodationCreate = components["schemas"]["AccommodationCreate"];
export type AccommodationResponse = components["schemas"]["AccommodationResponse"];
export type AccommodationChargeVersionCreate =
	components["schemas"]["AccommodationChargeVersionCreate"];
export type AccommodationChargeVersionResponse =
	components["schemas"]["AccommodationChargeVersionResponse"];
export type QuartersLocation = components["schemas"]["QuartersLocation"];

export const ADVANCE_TYPES: AdvanceType[] = [
	"hba",
	"gpf_advance",
	"festival",
	"motor_car",
	"motorcycle",
	"other",
];

export const QUARTERS_LOCATIONS: QuartersLocation[] = ["mumbai", "worli", "other"];

export function advanceTypeLabel(value: string): string {
	switch (value) {
		case "hba":
			return "HBA";
		case "gpf_advance":
			return "GPF advance";
		case "festival":
			return "Festival";
		case "motor_car":
			return "Motor car";
		case "motorcycle":
			return "Motorcycle";
		case "other":
			return "Other";
		default:
			return value
				.split("_")
				.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
				.join(" ");
	}
}

export function quartersLocationLabel(value: string): string {
	switch (value) {
		case "mumbai":
			return "Mumbai";
		case "worli":
			return "Worli";
		case "other":
			return "Other";
		default:
			return value.charAt(0).toUpperCase() + value.slice(1);
	}
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

export const employeePayrollSetupQueryKeys = {
	all: () => ["employee-payroll-setup"] as const,
	recurringInstructions: (employeeId: string, asOf?: string | null) =>
		[
			"employee-payroll-setup",
			"recurring-instructions",
			employeeId,
			{ as_of: asOf ?? null },
		] as const,
	advances: (employeeId: string, asOf?: string | null) =>
		["employee-payroll-setup", "advances", employeeId, { as_of: asOf ?? null }] as const,
	accommodation: (employeeId: string, asOf?: string | null) =>
		["employee-payroll-setup", "accommodation", employeeId, { as_of: asOf ?? null }] as const,
};

export function listRecurringInstructions(employeeId: string, asOf?: string | null) {
	const qs = buildQueryString({ as_of: asOf });
	return fetchJson<RecurringInstructionResponse[]>(
		`/api/employees/${employeeId}/recurring-instructions${qs}`,
	);
}

export function createRecurringInstruction(employeeId: string, body: RecurringInstructionCreate) {
	return fetchJson<RecurringInstructionResponse>(
		`/api/employees/${employeeId}/recurring-instructions`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(body),
		},
	);
}

export function createRecurringInstructionVersion(
	instructionId: string,
	body: RecurringInstructionVersionCreate,
) {
	return fetchJson<RecurringInstructionVersionResponse>(
		`/api/recurring-instructions/${instructionId}/versions`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(body),
		},
	);
}

export function listAdvances(employeeId: string, asOf?: string | null) {
	const qs = buildQueryString({ as_of: asOf });
	return fetchJson<AdvanceResponse[]>(`/api/employees/${employeeId}/advances${qs}`);
}

export function createAdvance(employeeId: string, body: AdvanceCreate) {
	return fetchJson<AdvanceResponse>(`/api/employees/${employeeId}/advances`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function createAdvanceInstallmentVersion(
	advanceId: string,
	body: AdvanceInstallmentVersionCreate,
) {
	return fetchJson<AdvanceInstallmentVersionResponse>(
		`/api/advances/${advanceId}/installment-versions`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(body),
		},
	);
}

export function listAccommodation(employeeId: string, asOf?: string | null) {
	const qs = buildQueryString({ as_of: asOf });
	return fetchJson<AccommodationResponse[]>(`/api/employees/${employeeId}/accommodation${qs}`);
}

export function createAccommodation(employeeId: string, body: AccommodationCreate) {
	return fetchJson<AccommodationResponse>(`/api/employees/${employeeId}/accommodation`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function createAccommodationChargeVersion(
	assignmentId: string,
	body: AccommodationChargeVersionCreate,
) {
	return fetchJson<AccommodationChargeVersionResponse>(
		`/api/accommodation/${assignmentId}/charge-versions`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(body),
		},
	);
}

export function useRecurringInstructions(employeeId: string | undefined, asOf?: string | null) {
	return useQuery({
		queryKey: employeePayrollSetupQueryKeys.recurringInstructions(employeeId ?? "", asOf),
		queryFn: () => listRecurringInstructions(employeeId!, asOf),
		enabled: Boolean(employeeId),
	});
}

export function useCreateRecurringInstruction(employeeId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (body: RecurringInstructionCreate) => createRecurringInstruction(employeeId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({
				queryKey: employeePayrollSetupQueryKeys.all(),
			});
		},
	});
}

export function useCreateRecurringInstructionVersion(_employeeId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({
			instructionId,
			body,
		}: {
			instructionId: string;
			body: RecurringInstructionVersionCreate;
		}) => createRecurringInstructionVersion(instructionId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({
				queryKey: employeePayrollSetupQueryKeys.all(),
			});
		},
	});
}

export function useAdvances(employeeId: string | undefined, asOf?: string | null) {
	return useQuery({
		queryKey: employeePayrollSetupQueryKeys.advances(employeeId ?? "", asOf),
		queryFn: () => listAdvances(employeeId!, asOf),
		enabled: Boolean(employeeId),
	});
}

export function useCreateAdvance(employeeId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (body: AdvanceCreate) => createAdvance(employeeId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({
				queryKey: employeePayrollSetupQueryKeys.all(),
			});
		},
	});
}

export function useCreateAdvanceInstallmentVersion(_employeeId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({
			advanceId,
			body,
		}: {
			advanceId: string;
			body: AdvanceInstallmentVersionCreate;
		}) => createAdvanceInstallmentVersion(advanceId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({
				queryKey: employeePayrollSetupQueryKeys.all(),
			});
		},
	});
}

export function useAccommodation(employeeId: string | undefined, asOf?: string | null) {
	return useQuery({
		queryKey: employeePayrollSetupQueryKeys.accommodation(employeeId ?? "", asOf),
		queryFn: () => listAccommodation(employeeId!, asOf),
		enabled: Boolean(employeeId),
	});
}

export function useCreateAccommodation(employeeId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: (body: AccommodationCreate) => createAccommodation(employeeId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({
				queryKey: employeePayrollSetupQueryKeys.all(),
			});
		},
	});
}

export function useCreateAccommodationChargeVersion(_employeeId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({
			assignmentId,
			body,
		}: {
			assignmentId: string;
			body: AccommodationChargeVersionCreate;
		}) => createAccommodationChargeVersion(assignmentId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({
				queryKey: employeePayrollSetupQueryKeys.all(),
			});
		},
	});
}
