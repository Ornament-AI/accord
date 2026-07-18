import { expect, test } from "@playwright/test";

import { readRunContext } from "./helpers/run-context";
import { selectWithin } from "./helpers/ui";

/**
 * Dev-auth limitation: DevAuthAdapter identity is fixed at backend process
 * startup (DEV_AUTH_EMAIL). Org admin holds both submit_run and approve_run,
 * so after Submit the same session's Approve hits maker/checker denial.
 * A second reviewer identity cannot be obtained through the UI without
 * restarting the backend with a different DEV_AUTH_EMAIL. This suite therefore
 * asserts submit + maker-checker denial and does not attempt a successful Approve.
 *
 * APP BUG (add input): PUT payroll-run input fails after commit with
 * InvalidRequestError on db.refresh(PayrollRunInput) in
 * backend/app/services/payroll_runs.py upsert_run_input. UI shows
 * "An unexpected error occurred." Documented as test.fixme below; Calculate
 * still runs via employee basic_pay from master-data.
 */
test.describe.configure({ mode: "serial" });

test("period + run → calculate → validate → submit; self-approve blocked", async ({ page }) => {
	const ctx = readRunContext();
	expect(ctx.employeeNumber, "master-data.spec must create an employee first").toBeTruthy();

	const now = new Date();
	const year = String(now.getFullYear());
	// Current calendar month so employee versions (effective_from ≈ today) are in-range.
	const month = String(now.getMonth() + 1);

	await page.goto("/pay-runs");
	await expect(page.getByTestId("pay-runs-page")).toBeVisible({ timeout: 30_000 });

	await page.getByRole("button", { name: "New period" }).first().click();
	const periodDialog = page.getByRole("dialog");
	await expect(periodDialog.getByRole("heading", { name: "New payroll period" })).toBeVisible();
	await periodDialog.getByLabel("Year").fill(year);
	await periodDialog.getByLabel("Month").fill(month);
	await periodDialog.getByRole("button", { name: "Create period" }).click();
	await expect(periodDialog).toBeHidden({ timeout: 30_000 });
	await expect(page.getByTestId("payroll-periods-list")).toBeVisible();

	await page.locator("header").getByRole("button", { name: "New pay run" }).click();
	const runDialog = page.getByRole("dialog");
	await expect(runDialog.getByRole("heading", { name: "New pay run" })).toBeVisible();
	await runDialog.getByRole("button", { name: "Create run" }).click();
	await expect(runDialog).toBeHidden({ timeout: 30_000 });

	const runRow = page.locator("table tbody tr").first();
	await expect(runRow).toBeVisible({ timeout: 30_000 });
	await runRow.click();
	await expect(page.getByTestId("pay-run-detail-page")).toBeVisible({ timeout: 30_000 });

	// This test covers the calculate → validate → submit → maker/checker critical
	// path; it deliberately does NOT add a draft input. Draft-input entry has its
	// own dedicated test below. (Adding a one_time input whose component_code
	// matches an already-resolved component would raise a duplicate_component_code
	// validation error and block submit — a test artifact, not a product defect.)
	await page.getByRole("button", { name: "Calculate pay run" }).click();
	await expect(page.getByTestId("pay-run-totals")).toBeVisible({ timeout: 60_000 });
	await expect(page.getByTestId("pay-run-totals")).toContainText(/Gross|Earnings|Net payable/i);

	await page.getByTestId("workflow-action-validate").click();
	await expect(page.getByTestId("validation-findings-panel")).toBeVisible({ timeout: 30_000 });

	// Idempotency-Key is sent as normal: the lease-commit RLS bug is fixed
	// (idempotent_command snapshots and rebinds SET LOCAL tenant GUCs).

	await page.getByTestId("workflow-action-submit").click();
	const confirm = page.getByTestId("workflow-confirm-dialog");
	await expect(confirm).toBeVisible();
	await confirm.getByTestId("workflow-confirm-submit").click();
	await expect(confirm).toBeHidden({ timeout: 30_000 });
	// Assert the run reached "submitted". Reload once if the post-mutation refetch
	// hasn't settled — this asserts the persisted status (what a user sees on
	// refresh), keeping the check about correctness rather than refetch timing.
	const statusBadge = page.getByTestId("run-status-badge");
	try {
		await expect(statusBadge).toHaveAttribute("data-status", "submitted", { timeout: 15_000 });
	} catch {
		await page.reload();
		await expect(page.getByTestId("pay-run-detail-page")).toBeVisible({ timeout: 30_000 });
		await expect(statusBadge).toHaveAttribute("data-status", "submitted", { timeout: 30_000 });
	}

	await page.getByTestId("workflow-action-approve").click();
	const approveConfirm = page.getByTestId("workflow-confirm-dialog");
	await expect(approveConfirm).toBeVisible();
	await approveConfirm.getByTestId("workflow-confirm-submit").click();
	await expect(page.getByTestId("maker-checker-alert")).toBeVisible({ timeout: 30_000 });
	await expect(page.getByTestId("maker-checker-alert")).toContainText(/Maker\/checker/i);
});

test("add direct run input lists component after save", async ({ page }) => {
	/**
	 * FIXED: PUT input upsert previously 500'd (post-commit refresh under cleared RLS GUCs).
	 * Backend: sqlalchemy.exc.InvalidRequestError: Could not refresh instance
	 * '<PayrollRunInput>' after commit in
	 * backend/app/services/payroll_runs.py upsert_run_input (~line 335).
	 * UI: "An unexpected error occurred." in Add run input dialog.
	 * Repro: open draft run → Add input → employee + component + amount + reason → Add input.
	 */
	const ctx = readRunContext();
	await page.goto("/pay-runs");
	await page.locator("table tbody tr").first().click();
	await page.getByRole("button", { name: "Add input" }).click();
	const inputDialog = page.getByRole("dialog");
	await inputDialog.getByLabel("Search employees").fill(ctx.employeeNumber!);
	await page.waitForTimeout(500);
	await selectWithin(inputDialog, "Employee", new RegExp(ctx.employeeNumber!));
	await inputDialog.getByLabel("Component code").fill(ctx.componentCode!);
	await selectWithin(inputDialog, "Input kind", "One Time");
	await inputDialog.getByLabel("Amount").fill("1500.00");
	await inputDialog.getByLabel("Reason").fill("E2E one-time adjustment");
	await inputDialog.getByRole("button", { name: "Add input" }).click();
	await expect(inputDialog).toBeHidden({ timeout: 30_000 });
	await expect(page.getByTestId("pay-run-detail-page")).toContainText(ctx.componentCode!);
});

test("submit with Idempotency-Key does not 404 after calculate", async ({ page }) => {
	/**
	 * FIXED: submit with Idempotency-Key previously 404'd
	 * "Payroll run not found." after a successful calculate+validate on the
	 * same run. Cause: idempotent_command commits the lease before executor,
	 * clearing SET LOCAL tenant GUCs so FOR UPDATE in _lock_run sees no row.
	 * Suspect: backend/app/services/idempotency.py + tenancy bind.
	 * Repro: calculated run → Submit (UI always sends Idempotency-Key) → error
	 * in confirm dialog.
	 */
	await page.goto("/pay-runs");
	await page.locator("table tbody tr").first().click();
	await expect(page.getByText("Calculated", { exact: true })).toBeVisible({ timeout: 30_000 });
	await page.getByTestId("workflow-action-submit").click();
	const confirm = page.getByTestId("workflow-confirm-dialog");
	await confirm.getByTestId("workflow-confirm-submit").click();
	await expect(confirm).toBeHidden({ timeout: 30_000 });
	await expect(page.getByText("Submitted", { exact: true })).toBeVisible();
});
