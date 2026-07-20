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

export type AccessState = "unbootstrapped" | "unprovisioned" | "active";

export type MeOrganization = {
	id: string;
	name: string;
	slug: string;
};

export type MeMembership = {
	role: Role | string;
	capabilities: Capability[] | string[];
};

export type AuthUser = {
	id: string;
	email: string;
	name: string;
	is_platform_admin: boolean;
};

/** Response shape for GET /api/auth/me (ADR 0011 singular contract). */
export type AuthMeResponse = {
	id: string;
	email: string;
	name: string;
	is_platform_admin: boolean;
	access_state: AccessState;
	organization: MeOrganization | null;
	membership: MeMembership | null;
};

/** @deprecated Use MeOrganization + MeMembership; kept for transitional UI helpers. */
export type OrganizationMembership = MeOrganization & {
	role: Role | string;
};

/** Active org view for capability checks (organization + membership). */
export type ActiveOrganization = MeOrganization & {
	role: Role | string;
	capabilities: Capability[] | string[];
};
