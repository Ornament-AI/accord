/** Organization membership roles from the frozen auth contract. */
export type Role =
	| "organization_administrator"
	| "payroll_preparer"
	| "payroll_reviewer"
	| "payroll_approver"
	| "report_releaser"
	| "auditor";

/** Capability strings granted on the active organization. */
export type Capability =
	| "manage_organization"
	| "manage_members"
	| "manage_master_data"
	| "view_master_data"
	| "reveal_sensitive_fields"
	| "create_run"
	| "submit_run"
	| "approve_run"
	| "post_run"
	| "generate_reports"
	| "release_reports"
	| "view_audit";

export type OrganizationMembership = {
	id: string;
	name: string;
	slug: string;
	role: Role | string;
};

export type ActiveOrganization = OrganizationMembership & {
	capabilities: Capability[] | string[];
};

export type AuthUser = {
	id: string;
	email: string;
	name: string;
	is_platform_admin: boolean;
};

/** Response shape for GET /api/auth/me, switch-organization, and create organization. */
export type AuthMeResponse = {
	id: string;
	email: string;
	name: string;
	is_platform_admin: boolean;
	active_organization: ActiveOrganization | null;
	organizations: OrganizationMembership[];
};

export type CreateOrganizationInput = {
	name: string;
	slug: string;
};

export type SwitchOrganizationInput = {
	organization_id: string;
};
