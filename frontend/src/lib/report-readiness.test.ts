import { describe, expect, it } from "vitest";

import type { ReportReadinessIssue } from "./report-readiness";
import { groupReadinessIssues, reportReadinessAction } from "./report-readiness";

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

describe("groupReadinessIssues", () => {
	it("collapses identical issues retagged per sheet into one row with a count", () => {
		const makeIssue = (report_type: string, message: string): ReportReadinessIssue => ({
			report_type,
			code: "approving_officer_signatory_missing",
			message,
			owner: "organization_export_settings",
			href: "/pay-components?reportDefaults=1",
		});
		const issues = [
			makeIssue("treasury_face", "Approving officer signatory name and designation are required."),
			makeIssue(
				"bank_rtgs_advice",
				"Approving officer signatory name and designation are required.",
			),
			makeIssue("approval_note", "Approving officer signatory name and designation are required."),
			makeIssue("treasury_face", "Final approver signatory name and designation are required."),
			makeIssue("payslips", "Final approver signatory name and designation are required."),
		];
		expect(groupReadinessIssues(issues).map(({ sheetCount }) => sheetCount)).toEqual([3, 2]);
	});

	it("counts distinct report sheets, not duplicate lines on one sheet", () => {
		const makeIssue = (report_type: string): ReportReadinessIssue => ({
			report_type,
			code: "employee_nps_identifier_missing",
			message: "Employee S0001 is missing pension account.",
			owner: "employee",
			entity_id: "emp-1",
			href: "/employees/emp-1",
		});
		// The readiness API re-emits the same defect for each NPS result line —
		// both land on the same sheet, so the count must stay 1.
		const grouped = groupReadinessIssues([
			makeIssue("nps_contribution_schedule"),
			makeIssue("nps_contribution_schedule"),
		]);
		expect(grouped).toHaveLength(1);
		expect(grouped[0].sheetCount).toBe(1);
	});

	it("keeps per-entity issues separate so each fix stays actionable", () => {
		const makeIssue = (entity_id: string): ReportReadinessIssue => ({
			report_type: "pay_bill",
			code: "employee_bank_account_missing",
			message: "Employee bank account is missing",
			owner: "employee",
			entity_id,
			href: `/employees/${entity_id}`,
		});
		const grouped = groupReadinessIssues([makeIssue("emp-1"), makeIssue("emp-2")]);
		expect(grouped).toHaveLength(2);
		expect(grouped.every(({ sheetCount }) => sheetCount === 1)).toBe(true);
	});

	it("gives each group a stable key that separates same-code different-message rows", () => {
		const makeIssue = (message: string): ReportReadinessIssue => ({
			report_type: "pay_bill",
			code: "pay_bill_page_capacity",
			message,
			owner: "post_catalog",
			href: "/organization/posts",
			entity_id: "run-1",
		});
		const grouped = groupReadinessIssues([
			makeIssue("Pay Bill pages after serial 8 overflow."),
			makeIssue("Pay Bill pages after serial 18 overflow."),
		]);
		expect(grouped).toHaveLength(2);
		expect(new Set(grouped.map(({ key }) => key)).size).toBe(2);
	});
});
