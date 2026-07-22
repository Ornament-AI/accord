import { describe, expect, it } from "vitest";

import { reportReadinessAction } from "./report-readiness";

describe("reportReadinessAction", () => {
	it.each([
		["bill_number_missing", "run_report_details", "Open run report details", "/pay-runs/run-1"],
		[
			"ddo_code_missing",
			"organization_export_settings",
			"Open report defaults",
			"/pay-components?reportDefaults=1",
		],
		["sanctioned_strength_missing", "post_catalog", "Open post catalog", "/organization/posts"],
		["register_column_missing", "pay_component_catalog", "Open pay components", "/pay-components"],
		["employee_bank_account_missing", "employee", "Open employee records", "/employees"],
	])("maps %s to its owning surface", (code, owner, label, to) => {
		expect(
			reportReadinessAction(
				{ report_type: "pay_bill", code, message: "Missing canonical field", owner, href: to },
				"run-1",
			),
		).toEqual({ label, to });
	});

	it("uses a supplied employee entity id when the settled schema provides one", () => {
		expect(
			reportReadinessAction(
				{
					report_type: "pay_bill",
					code: "profile_missing",
					message: "Employee profile is incomplete",
					owner: "employee",
					entity_id: "emp-7",
					href: "/employees/emp-7?section=payroll",
				},
				"run-1",
			),
		).toEqual({ label: "Open employee records", to: "/employees/emp-7?section=payroll" });
	});

	it("lets the explicit organization owner override an employee-like code", () => {
		expect(
			reportReadinessAction(
				{
					report_type: "gpf_mumbai_schedule",
					code: "gpf_mumbai_office_name_missing",
					message: "Mumbai GPF office name is missing",
					owner: "organization_export_settings",
					href: "/pay-components?reportDefaults=1",
				},
				"run-1",
			),
		).toEqual({ label: "Open report defaults", to: "/pay-components?reportDefaults=1" });
	});

	it("rejects external-looking readiness hrefs and uses the owner fallback", () => {
		expect(
			reportReadinessAction(
				{
					report_type: "pay_bill",
					code: "post_missing",
					message: "Post details are missing",
					owner: "post_catalog",
					href: "//example.test/redirect",
				},
				"run-1",
			),
		).toEqual({ label: "Open post catalog", to: "/organization/posts" });
	});
});
