import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJson, jsonRequest } from "@/lib/api/http";
import { buildQueryString } from "@/lib/api/query-utils";
import type { components } from "@/types/api.generated";

export type EmployeeSummary = components["schemas"]["EmployeeSummary"];
export type EmployeeDetail = components["schemas"]["EmployeeDetail"];
export type CreateEmployeeRequest = components["schemas"]["CreateEmployeeRequest"];
export type PaginatedEmployeeSummary = components["schemas"]["PaginatedResponse_EmployeeSummary_"];
export type ProfileInput = components["schemas"]["ProfileInput"];
export type PostingInput = components["schemas"]["PostingInput"];
export type PayInput = components["schemas"]["PayInput"];
export type BankInput = components["schemas"]["BankInput"];
export type ProfileVersionResponse = components["schemas"]["ProfileVersionResponse"];
export type PostingVersionResponse = components["schemas"]["PostingVersionResponse"];
export type PayVersionResponse = components["schemas"]["PayVersionResponse"];
export type BankVersionResponse = components["schemas"]["BankVersionResponse"];
export type RetirementRegime = components["schemas"]["RetirementRegime"];
export type GpfJurisdiction = components["schemas"]["GpfJurisdiction"];

export type EmployeeVersionKind = "profile" | "posting" | "pay" | "bank";

export type ListEmployeesParams = {
	as_of?: string | null;
	search?: string | null;
	page?: number;
	size?: number;
	reveal?: boolean;
};

export type GetEmployeeParams = {
	as_of?: string | null;
	reveal?: boolean;
};

export type CreateEmployeeVersionBody = Record<string, unknown>;

export const employeeQueryKeys = {
	all: () => ["employees"] as const,
	list: (params: ListEmployeesParams) => ["employees", "list", params] as const,
	detail: (employeeId: string, params: GetEmployeeParams) =>
		["employees", "detail", employeeId, params] as const,
	versions: (employeeId: string, kind: EmployeeVersionKind, reveal: boolean) =>
		["employees", "versions", employeeId, kind, { reveal }] as const,
};

export function listEmployees(params: ListEmployeesParams = {}) {
	const qs = buildQueryString({
		as_of: params.as_of,
		search: params.search,
		page: params.page,
		size: params.size,
		reveal: params.reveal === true ? true : undefined,
	});
	return fetchJson<PaginatedEmployeeSummary>(`/api/employees${qs}`);
}

export function getEmployee(employeeId: string, params: GetEmployeeParams = {}) {
	const qs = buildQueryString({
		as_of: params.as_of,
		reveal: params.reveal === true ? true : undefined,
	});
	return fetchJson<EmployeeDetail>(`/api/employees/${employeeId}${qs}`);
}

export function createEmployee(body: CreateEmployeeRequest) {
	return fetchJson<EmployeeDetail>("/api/employees", jsonRequest("POST", body));
}

export function listEmployeeVersions(
	employeeId: string,
	kind: EmployeeVersionKind,
	params: { reveal?: boolean } = {},
) {
	const qs = buildQueryString({
		reveal: params.reveal === true ? true : undefined,
	});
	return fetchJson<unknown[]>(`/api/employees/${employeeId}/versions/${kind}${qs}`);
}

export function createEmployeeVersion(
	employeeId: string,
	kind: EmployeeVersionKind,
	body: CreateEmployeeVersionBody,
) {
	return fetchJson<unknown>(
		`/api/employees/${employeeId}/versions/${kind}`,
		jsonRequest("POST", body),
	);
}

export function useEmployeesList(params: ListEmployeesParams) {
	return useQuery({
		queryKey: employeeQueryKeys.list(params),
		queryFn: () => listEmployees(params),
		placeholderData: (previous) => previous,
	});
}

export function useEmployeeDetail(employeeId: string | undefined, params: GetEmployeeParams) {
	return useQuery({
		queryKey: employeeQueryKeys.detail(employeeId ?? "", params),
		queryFn: () => getEmployee(employeeId!, params),
		enabled: Boolean(employeeId),
	});
}

export function useEmployeeVersions(
	employeeId: string | undefined,
	kind: EmployeeVersionKind,
	reveal: boolean,
) {
	return useQuery({
		queryKey: employeeQueryKeys.versions(employeeId ?? "", kind, reveal),
		queryFn: () => listEmployeeVersions(employeeId!, kind, { reveal }),
		enabled: Boolean(employeeId),
	});
}

export function useCreateEmployee() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: createEmployee,
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: employeeQueryKeys.all() });
		},
	});
}

export function useCreateEmployeeVersion(employeeId: string) {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({ kind, body }: { kind: EmployeeVersionKind; body: CreateEmployeeVersionBody }) =>
			createEmployeeVersion(employeeId, kind, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: employeeQueryKeys.all() });
		},
	});
}

/** Compatibility exports for existing employee screens. */
