import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJson } from "@/lib/api/http";
import type { components } from "@/types/api.generated";

export type OfficeResponse = components["schemas"]["OfficeResponse"];
export type OfficeCreate = components["schemas"]["OfficeCreate"];
export type OfficeUpdate = components["schemas"]["OfficeUpdate"];

export type PayrollUnitResponse = components["schemas"]["PayrollUnitResponse"];
export type PayrollUnitCreate = components["schemas"]["PayrollUnitCreate"];
export type PayrollUnitUpdate = components["schemas"]["PayrollUnitUpdate"];

export type PostResponse = components["schemas"]["PostResponse"];
export type PostCreate = components["schemas"]["PostCreate"];
export type PostUpdate = components["schemas"]["PostUpdate"];

export type EmployeeGroupResponse = components["schemas"]["EmployeeGroupResponse"];
export type EmployeeGroupCreate = components["schemas"]["EmployeeGroupCreate"];
export type EmployeeGroupUpdate = components["schemas"]["EmployeeGroupUpdate"];

export type OrganizationSettingsResponse = components["schemas"]["OrganizationSettingsResponse"];
export type OrganizationSettingsUpdate = components["schemas"]["OrganizationSettingsUpdate"];

export type OfficeJurisdiction = OfficeCreate["jurisdiction"];

export const orgStructureQueryKeys = {
	all: () => ["org-structure"] as const,
	offices: () => ["org-structure", "offices"] as const,
	payrollUnits: () => ["org-structure", "payroll-units"] as const,
	posts: () => ["org-structure", "posts"] as const,
	employeeGroups: () => ["org-structure", "employee-groups"] as const,
	organizationSettings: () => ["org-structure", "organization-settings"] as const,
};

export function listOffices() {
	return fetchJson<OfficeResponse[]>("/api/offices");
}

export function createOffice(body: OfficeCreate) {
	return fetchJson<OfficeResponse>("/api/offices", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function updateOffice(officeId: string, body: OfficeUpdate) {
	return fetchJson<OfficeResponse>(`/api/offices/${officeId}`, {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function listPayrollUnits() {
	return fetchJson<PayrollUnitResponse[]>("/api/payroll-units");
}

export function createPayrollUnit(body: PayrollUnitCreate) {
	return fetchJson<PayrollUnitResponse>("/api/payroll-units", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function updatePayrollUnit(payrollUnitId: string, body: PayrollUnitUpdate) {
	return fetchJson<PayrollUnitResponse>(`/api/payroll-units/${payrollUnitId}`, {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function listPosts() {
	return fetchJson<PostResponse[]>("/api/posts");
}

export function createPost(body: PostCreate) {
	return fetchJson<PostResponse>("/api/posts", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function updatePost(postId: string, body: PostUpdate) {
	return fetchJson<PostResponse>(`/api/posts/${postId}`, {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function listEmployeeGroups() {
	return fetchJson<EmployeeGroupResponse[]>("/api/employee-groups");
}

export function createEmployeeGroup(body: EmployeeGroupCreate) {
	return fetchJson<EmployeeGroupResponse>("/api/employee-groups", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function updateEmployeeGroup(employeeGroupId: string, body: EmployeeGroupUpdate) {
	return fetchJson<EmployeeGroupResponse>(`/api/employee-groups/${employeeGroupId}`, {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function getOrganizationSettings() {
	return fetchJson<OrganizationSettingsResponse>("/api/organization-settings");
}

export function updateOrganizationSettings(body: OrganizationSettingsUpdate) {
	return fetchJson<OrganizationSettingsResponse>("/api/organization-settings", {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function useOfficesList() {
	return useQuery({
		queryKey: orgStructureQueryKeys.offices(),
		queryFn: listOffices,
	});
}

export function useCreateOffice() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: createOffice,
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: orgStructureQueryKeys.offices() });
		},
	});
}

export function useUpdateOffice() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({ officeId, body }: { officeId: string; body: OfficeUpdate }) =>
			updateOffice(officeId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: orgStructureQueryKeys.offices() });
		},
	});
}

export function usePayrollUnitsList() {
	return useQuery({
		queryKey: orgStructureQueryKeys.payrollUnits(),
		queryFn: listPayrollUnits,
	});
}

export function useCreatePayrollUnit() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: createPayrollUnit,
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: orgStructureQueryKeys.payrollUnits() });
		},
	});
}

export function useUpdatePayrollUnit() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({ payrollUnitId, body }: { payrollUnitId: string; body: PayrollUnitUpdate }) =>
			updatePayrollUnit(payrollUnitId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: orgStructureQueryKeys.payrollUnits() });
		},
	});
}

export function usePostsList() {
	return useQuery({
		queryKey: orgStructureQueryKeys.posts(),
		queryFn: listPosts,
	});
}

export function useCreatePost() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: createPost,
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: orgStructureQueryKeys.posts() });
		},
	});
}

export function useUpdatePost() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({ postId, body }: { postId: string; body: PostUpdate }) =>
			updatePost(postId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: orgStructureQueryKeys.posts() });
		},
	});
}

export function useEmployeeGroupsList() {
	return useQuery({
		queryKey: orgStructureQueryKeys.employeeGroups(),
		queryFn: listEmployeeGroups,
	});
}

export function useCreateEmployeeGroup() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: createEmployeeGroup,
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: orgStructureQueryKeys.employeeGroups() });
		},
	});
}

export function useUpdateEmployeeGroup() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({
			employeeGroupId,
			body,
		}: {
			employeeGroupId: string;
			body: EmployeeGroupUpdate;
		}) => updateEmployeeGroup(employeeGroupId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: orgStructureQueryKeys.employeeGroups() });
		},
	});
}

export function useOrganizationSettings() {
	return useQuery({
		queryKey: orgStructureQueryKeys.organizationSettings(),
		queryFn: getOrganizationSettings,
	});
}

export function useUpdateOrganizationSettings() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: updateOrganizationSettings,
		onSuccess: () => {
			void queryClient.invalidateQueries({
				queryKey: orgStructureQueryKeys.organizationSettings(),
			});
		},
	});
}
