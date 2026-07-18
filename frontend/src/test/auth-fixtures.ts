import type { AuthMeResponse, Capability, Role } from "@/types/auth";

/** Test-only role → capability matrix (backend mapping is not in the frozen contract). */
export const ROLE_CAPABILITIES: Record<Role, Capability[]> = {
	organization_administrator: [
		"manage_organization",
		"manage_members",
		"manage_master_data",
		"view_master_data",
		"reveal_sensitive_fields",
		"create_run",
		"submit_run",
		"approve_run",
		"post_run",
		"generate_reports",
		"release_reports",
		"view_audit",
	],
	payroll_preparer: ["view_master_data", "create_run", "submit_run"],
	payroll_reviewer: ["view_master_data", "approve_run"],
	payroll_approver: ["view_master_data", "approve_run", "post_run"],
	report_releaser: ["generate_reports", "release_reports"],
	auditor: ["view_master_data", "view_audit", "generate_reports"],
};

export function buildAuthMe(overrides: Partial<AuthMeResponse> = {}): AuthMeResponse {
	const orgId = "org-acme";
	const role: Role = "organization_administrator";
	const base: AuthMeResponse = {
		id: "user-1",
		email: "ada@example.com",
		name: "Ada Lovelace",
		is_platform_admin: false,
		active_organization: {
			id: orgId,
			name: "Acme Payroll",
			slug: "acme-payroll",
			role,
			capabilities: ROLE_CAPABILITIES[role],
		},
		organizations: [
			{
				id: orgId,
				name: "Acme Payroll",
				slug: "acme-payroll",
				role,
			},
			{
				id: "org-beta",
				name: "Beta Co",
				slug: "beta-co",
				role: "auditor",
			},
		],
	};

	return {
		...base,
		...overrides,
		active_organization:
			overrides.active_organization === undefined
				? base.active_organization
				: overrides.active_organization,
		organizations: overrides.organizations ?? base.organizations,
	};
}

export function buildNoOrgAuthMe(overrides: Partial<AuthMeResponse> = {}): AuthMeResponse {
	return buildAuthMe({
		active_organization: null,
		organizations: [],
		...overrides,
	});
}

export function buildRoleAuthMe(role: Role, organizationId = "org-acme"): AuthMeResponse {
	return buildAuthMe({
		active_organization: {
			id: organizationId,
			name: "Acme Payroll",
			slug: "acme-payroll",
			role,
			capabilities: ROLE_CAPABILITIES[role],
		},
		organizations: [
			{
				id: organizationId,
				name: "Acme Payroll",
				slug: "acme-payroll",
				role,
			},
		],
	});
}
