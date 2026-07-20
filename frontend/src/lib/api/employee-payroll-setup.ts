/** Employee-scoped payroll setup: recurring instructions, advances, accommodation. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJson, jsonRequest } from "@/lib/api/http";
import { buildQueryString } from "@/lib/api/query-utils";
import type { components } from "@/types/api.generated";

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
		jsonRequest("POST", body),
	);
}

export function createRecurringInstructionVersion(
	instructionId: string,
	body: RecurringInstructionVersionCreate,
) {
	return fetchJson<RecurringInstructionVersionResponse>(
		`/api/recurring-instructions/${instructionId}/versions`,
		jsonRequest("POST", body),
	);
}

export function listAdvances(employeeId: string, asOf?: string | null) {
	const qs = buildQueryString({ as_of: asOf });
	return fetchJson<AdvanceResponse[]>(`/api/employees/${employeeId}/advances${qs}`);
}

export function createAdvance(employeeId: string, body: AdvanceCreate) {
	return fetchJson<AdvanceResponse>(
		`/api/employees/${employeeId}/advances`,
		jsonRequest("POST", body),
	);
}

export function createAdvanceInstallmentVersion(
	advanceId: string,
	body: AdvanceInstallmentVersionCreate,
) {
	return fetchJson<AdvanceInstallmentVersionResponse>(
		`/api/advances/${advanceId}/installment-versions`,
		jsonRequest("POST", body),
	);
}

export function listAccommodation(employeeId: string, asOf?: string | null) {
	const qs = buildQueryString({ as_of: asOf });
	return fetchJson<AccommodationResponse[]>(`/api/employees/${employeeId}/accommodation${qs}`);
}

export function createAccommodation(employeeId: string, body: AccommodationCreate) {
	return fetchJson<AccommodationResponse>(
		`/api/employees/${employeeId}/accommodation`,
		jsonRequest("POST", body),
	);
}

export function createAccommodationChargeVersion(
	assignmentId: string,
	body: AccommodationChargeVersionCreate,
) {
	return fetchJson<AccommodationChargeVersionResponse>(
		`/api/accommodation/${assignmentId}/charge-versions`,
		jsonRequest("POST", body),
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
