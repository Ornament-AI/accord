import type { ReportReadinessResponse } from "@/lib/api/payroll-runs";

export type ReportReadinessIssue = ReportReadinessResponse["issues"][number];

export type ReportReadinessAction = { label: string; to: string };

function safeReadinessHref(href: string | undefined): string | null {
	if (!href?.startsWith("/") || href.startsWith("//")) return null;
	return href;
}

const RUN_DETAIL_CODES = [
	"bill_",
	"payment_",
	"demand_",
	"major_head",
	"sub_head",
	"detailed_head",
	"token_",
	"voucher_",
	"bank_advice_number",
	"approval_note_",
];
const ORGANIZATION_CODES = [
	"legal_name",
	"office_name",
	"address_",
	"cin_",
	"phone_",
	"website_",
	"ddo_",
	"department_",
	"administrative_department",
	"treasury_code",
	"fund_source",
	"plan_status",
	"salary_reference",
	"pay_bill_footer",
	"advice_bank",
];
const POST_CODES = ["post_", "sanctioned_strength", "vacant_count", "pay_scale"];
const COMPONENT_CODES = ["pay_component_", "component_", "register_column"];
const EMPLOYEE_CODES = [
	"employee_",
	"sevarth_",
	"date_of_birth",
	"date_of_joining",
	"posting_",
	"bank_account",
	"ifsc_",
	"pension_",
	"pran_",
	"gpf_",
	"epf_",
];

function includesCode(code: string, prefixes: readonly string[]): boolean {
	return prefixes.some((prefix) => code.includes(prefix));
}

export function reportReadinessAction(
	issue: ReportReadinessIssue,
	runId: string,
): ReportReadinessAction {
	const owner = issue.owner;
	const href = safeReadinessHref(issue.href);
	if (owner === "run_report_details") {
		return { label: "Open run report details", to: href ?? `/pay-runs/${runId}` };
	}
	if (owner === "post_catalog") {
		return { label: "Open post catalog", to: href ?? "/organization/posts" };
	}
	if (owner === "pay_component_catalog") {
		return { label: "Open pay components", to: href ?? "/pay-components" };
	}
	if (owner === "employee") {
		return {
			label: "Open employee records",
			to: href ?? (issue.entity_id ? `/employees/${issue.entity_id}` : "/employees"),
		};
	}
	if (owner === "organization_export_settings") {
		return { label: "Open report defaults", to: href ?? "/pay-components?reportDefaults=1" };
	}
	if (includesCode(issue.code, RUN_DETAIL_CODES)) {
		return { label: "Open run report details", to: href ?? `/pay-runs/${runId}` };
	}
	if (includesCode(issue.code, POST_CODES)) {
		return { label: "Open post catalog", to: href ?? "/organization/posts" };
	}
	if (includesCode(issue.code, COMPONENT_CODES)) {
		return { label: "Open pay components", to: href ?? "/pay-components" };
	}
	if (includesCode(issue.code, EMPLOYEE_CODES)) {
		return {
			label: "Open employee records",
			to: href ?? (issue.entity_id ? `/employees/${issue.entity_id}` : "/employees"),
		};
	}
	if (includesCode(issue.code, ORGANIZATION_CODES)) {
		return { label: "Open report defaults", to: href ?? "/pay-components?reportDefaults=1" };
	}
	return { label: "Open run report details", to: href ?? `/pay-runs/${runId}` };
}
