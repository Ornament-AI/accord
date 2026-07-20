import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJson, jsonRequest } from "@/lib/api/http";
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
	return fetchJson<PayrollExportProfileResponse>("/api/report-profile", jsonRequest("PUT", body));
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
	return fetchJson<PayComponentResponse>("/api/pay-components", jsonRequest("POST", body));
}

export function updatePayComponent(componentId: string, body: PayComponentUpdate) {
	return fetchJson<PayComponentResponse>(
		`/api/pay-components/${componentId}`,
		jsonRequest("PATCH", body),
	);
}

export function listComponentRateVersions(componentId: string) {
	return fetchJson<ComponentRateVersionResponse[]>(
		`/api/pay-components/${componentId}/rate-versions`,
	);
}

export function createComponentRateVersion(componentId: string, body: ComponentRateVersionCreate) {
	return fetchJson<ComponentRateVersionResponse>(
		`/api/pay-components/${componentId}/rate-versions`,
		jsonRequest("POST", body),
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
