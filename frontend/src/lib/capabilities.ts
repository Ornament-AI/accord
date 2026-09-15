import type { Capability } from "@/types/auth";

/**
 * Read-side capability union for the pay-run operator pages.
 * Backend run detail/roster reads additionally accept `generate_reports`
 * (see payroll_runs.py) — report consumers are served by the reports UI,
 * so the page gate keeps the lifecycle union; keep in sync with
 * backend/app/api/routes/payroll_runs.py.
 */
export const PAY_RUN_READ_CAPABILITIES = [
	"view_master_data",
	"create_run",
	"submit_run",
	"approve_run",
	"post_run",
] as const satisfies readonly Capability[];

/**
 * The payroll-runs list and report-readiness endpoints also serve report
 * consumers (e.g. `auditor`), so their gate additionally includes
 * `generate_reports`.
 */
export const PAY_RUN_REPORT_READ_CAPABILITIES = [
	...PAY_RUN_READ_CAPABILITIES,
	"generate_reports",
] as const satisfies readonly Capability[];
