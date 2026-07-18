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

export type PayComponentUpdate = {
	name?: string;
	display_order?: number;
	is_active?: boolean;
};

export const CLASSIFICATIONS: Classification[] = [
	"earning",
	"employer_contribution",
	"ag_deduction",
	"treasury_deduction",
	"gross_adjustment",
	"external_recovery",
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

export function classificationLabel(value: string): string {
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
};

export function listPayComponents() {
	return fetchJson<PayComponentResponse[]>("/api/pay-components");
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
