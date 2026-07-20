import type { AccessState, AuthMeResponse, Capability, Role } from "@/types/auth";

/** Test-only role → capability matrix (backend mapping is not in the frozen contract). */
// Mirrors the backend-authoritative matrix in backend/app/auth/capabilities.py.
export const ROLE_CAPABILITIES: Record<Role, Capability[]> = {
	organization_administrator: [
		"manage_organization",
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
	payroll_preparer: [
		"manage_master_data",
		"view_master_data",
		"create_run",
		"submit_run",
		"generate_reports",
		"view_audit",
	],
	payroll_reviewer: ["view_master_data", "generate_reports", "view_audit"],
	payroll_approver: ["approve_run", "generate_reports", "view_audit"],
	report_releaser: ["post_run", "generate_reports", "release_reports", "view_audit"],
	auditor: ["generate_reports", "view_audit"],
};

export function buildAuthMe(overrides: Partial<AuthMeResponse> = {}): AuthMeResponse {
	const orgId = "org-acme";
	const role: Role = "organization_administrator";
	const organization = {
		id: orgId,
		name: "Acme Payroll",
		slug: "acme-payroll",
	};
	const membership = {
		role,
		capabilities: ROLE_CAPABILITIES[role],
	};
	const base: AuthMeResponse = {
		id: "user-1",
		email: "ada@example.com",
		name: "Ada Lovelace",
		is_platform_admin: false,
		access_state: "active",
		organization,
		membership,
	};

	const merged: AuthMeResponse = {
		...base,
		...overrides,
		organization: overrides.organization === undefined ? base.organization : overrides.organization,
		membership: overrides.membership === undefined ? base.membership : overrides.membership,
		access_state: overrides.access_state === undefined ? base.access_state : overrides.access_state,
	};
	return merged;
}

export function buildNoOrgAuthMe(overrides: Partial<AuthMeResponse> = {}): AuthMeResponse {
	return buildAuthMe({
		access_state: "unbootstrapped",
		organization: null,
		membership: null,
		...overrides,
	});
}

export function buildUnprovisionedAuthMe(overrides: Partial<AuthMeResponse> = {}): AuthMeResponse {
	return buildAuthMe({
		access_state: "unprovisioned",
		membership: null,
		...overrides,
	});
}

export function buildRoleAuthMe(role: Role, organizationId = "org-acme"): AuthMeResponse {
	return buildAuthMe({
		access_state: "active",
		organization: {
			id: organizationId,
			name: "Acme Payroll",
			slug: "acme-payroll",
		},
		membership: {
			role,
			capabilities: ROLE_CAPABILITIES[role],
		},
	});
}

export type { AccessState };
