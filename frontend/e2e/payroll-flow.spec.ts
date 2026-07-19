import { expect, type Page, test } from "@playwright/test";

import { readRunContext } from "./helpers/run-context";
import { clickUntilDialog, selectWithin } from "./helpers/ui";

/**
 * Dev-auth limitation: DevAuthAdapter identity is fixed at backend process
 * startup (DEV_AUTH_EMAIL). Org admin holds both submit_run and approve_run,
 * so after Submit the same session's Approve hits maker/checker denial.
 * A second reviewer identity cannot be obtained through the UI without
 * restarting the backend with a different DEV_AUTH_EMAIL. This suite therefore
 * asserts submit + maker-checker denial and does not attempt a successful Approve.
 *
 * Regular pay runs are unique per period. The serial chain shares one regular
 * draft (add input → calculate/validate/submit). The Idempotency-Key case uses
 * a supplemental run so it does not collide with that unique constraint.
 */

test.describe.configure({ mode: "serial" });

function currentYearMonth(): { year: string; month: string } {
	const now = new Date();
	return {
		year: String(now.getFullYear()),
		// Current calendar month so employee versions (effective_from ≈ today) are in-range.
		month: String(now.getMonth() + 1),
	};
}

/** Create the current payroll period, or dismiss the dialog if it already exists. */
async function ensurePayrollPeriod(page: Page): Promise<void> {
	const { year, month } = currentYearMonth();
	await page.goto("/pay-runs");
	await expect(page.getByTestId("pay-runs-page")).toBeVisible({ timeout: 30_000 });

	const dialog = await clickUntilDialog(
		page,
		page.getByRole("button", { name: "New period" }).first(),
	);
	await expect(dialog.getByRole("heading", { name: "New Payroll Period" })).toBeVisible();
	await dialog.getByLabel("Year").fill(year);
	await dialog.getByLabel("Month").fill(month);
	await dialog.getByRole("button", { name: "Create period" }).click();

	const closed = await dialog
		.waitFor({ state: "hidden", timeout: 5_000 })
		.then(() => true)
		.catch(() => false);
	if (!closed) {
		await expect(dialog.getByRole("alert")).toBeVisible({ timeout: 5_000 });
		await dialog.getByRole("button", { name: "Cancel" }).click();
		await expect(dialog).toBeHidden({ timeout: 10_000 });
	}

	await expect(page.getByTestId("payroll-periods-list")).toBeVisible();
}

/**
 * Create a pay run (regular or supplemental). If a regular run already exists
 * for the period, cancel and open the newest matching list row instead.
 */
async function createOrOpenPayRun(
	page: Page,
	opts: { runType?: "regular" | "supplemental" } = {},
): Promise<void> {
	const runType = opts.runType ?? "regular";
	const typeLabel = runType === "supplemental" ? "Supplemental" : "Regular";
	const runDialog = await clickUntilDialog(
		page,
		page.locator("header").getByRole("button", { name: "New Pay Run" }),
	);
	await expect(runDialog.getByRole("heading", { name: "New Pay Run" })).toBeVisible();

	if (runType !== "regular") {
		await selectWithin(runDialog, "Run Type", typeLabel);
		// Trigger accessible text is the raw enum value ("supplemental"), not the label.
		await expect(runDialog.getByRole("combobox", { name: "Run Type" })).toContainText(
			new RegExp(runType, "i"),
		);
	}

	await runDialog.getByRole("button", { name: "Create run" }).click();

	const closed = await runDialog
		.waitFor({ state: "hidden", timeout: 5_000 })
		.then(() => true)
		.catch(() => false);
	if (!closed) {
		await expect(runDialog.getByRole("alert")).toBeVisible({ timeout: 5_000 });
		await runDialog.getByRole("button", { name: "Cancel" }).click();
		await expect(runDialog).toBeHidden({ timeout: 10_000 });
	}

	const runRow = page.locator("table tbody tr", { hasText: typeLabel }).first();
	await expect(runRow).toBeVisible({ timeout: 30_000 });
	await runRow.click();
	await expect(page.getByTestId("pay-run-detail-page")).toBeVisible({ timeout: 30_000 });
}

async function openNewestPayRun(page: Page): Promise<void> {
	await page.goto("/pay-runs");
	await expect(page.getByTestId("pay-runs-page")).toBeVisible({ timeout: 30_000 });
	const runRow = page.locator("table tbody tr").first();
	await expect(runRow).toBeVisible({ timeout: 30_000 });
	await runRow.click();
	await expect(page.getByTestId("pay-run-detail-page")).toBeVisible({ timeout: 30_000 });
}

async function calculateAndValidate(page: Page): Promise<void> {
	await page.getByRole("button", { name: "Calculate Pay Run" }).click();
	await expect(page.getByTestId("pay-run-totals")).toBeVisible({ timeout: 60_000 });
	await expect(page.getByTestId("pay-run-totals")).toContainText(/Gross|Earnings|Net Payable/i);

	await page.getByTestId("workflow-action-validate").click();
	await expect(page.getByTestId("validation-findings-panel")).toBeVisible({ timeout: 30_000 });
}

async function submitRun(page: Page): Promise<void> {
	await page.getByTestId("workflow-action-submit").click();
	const confirm = page.getByTestId("workflow-confirm-dialog");
	await expect(confirm).toBeVisible();
	await confirm.getByTestId("workflow-confirm-submit").click();
	await expect(confirm).toBeHidden({ timeout: 30_000 });
}

test("add direct run input lists component after save", async ({ page }) => {
	/**
	 * FIXED: PUT input upsert previously 500'd (post-commit refresh under cleared RLS GUCs).
	 * Backend: sqlalchemy.exc.InvalidRequestError: Could not refresh instance
	 * '<PayrollRunInput>' after commit in
	 * backend/app/services/payroll_runs.py upsert_run_input (~line 335).
	 * UI: "An unexpected error occurred." in Add Run Input dialog.
	 * Repro: open draft run → Add input → employee + component + amount + reason → Add input.
	 */
	const ctx = readRunContext();
	expect(ctx.employeeNumber, "master-data.spec must create an employee first").toBeTruthy();
	expect(ctx.componentCode, "master-data.spec must create a pay component first").toBeTruthy();

	await ensurePayrollPeriod(page);
	await createOrOpenPayRun(page, { runType: "regular" });

	const status = await page.getByTestId("run-status-badge").getAttribute("data-status");
	// Retry-safe: a prior worker may have already advanced this regular run.
	if (status !== "draft") {
		return;
	}

	const alreadyListed = await page
		.getByTestId("pay-run-detail-page")
		.getByText(ctx.componentCode!)
		.isVisible()
		.catch(() => false);
	if (alreadyListed) {
		return;
	}

	const inputDialog = await clickUntilDialog(page, page.getByRole("button", { name: "Add input" }));
	await inputDialog.getByLabel("Search Employees").fill(ctx.employeeNumber!);
	await page.waitForTimeout(500);
	await selectWithin(inputDialog, "Employee", new RegExp(ctx.employeeNumber!));
	await inputDialog.getByLabel("Component Code").fill(ctx.componentCode!);
	await selectWithin(inputDialog, "Input Kind", "One Time");
	await inputDialog.getByLabel("Amount").fill("1500.00");
	await inputDialog.getByLabel("Reason").fill("E2E one-time adjustment");
	await inputDialog.getByRole("button", { name: "Add input" }).click();
	await expect(inputDialog).toBeHidden({ timeout: 30_000 });
	await expect(page.getByTestId("pay-run-detail-page")).toContainText(ctx.componentCode!);
});

test("period + run → calculate → validate → submit; self-approve blocked", async ({ page }) => {
	const ctx = readRunContext();
	expect(ctx.employeeNumber, "master-data.spec must create an employee first").toBeTruthy();

	// Reuse the regular draft from the add-input test (regular is unique per period).
	await openNewestPayRun(page);

	const status = await page.getByTestId("run-status-badge").getAttribute("data-status");
	if (status === "draft" || status === "calculated" || status === "rejected") {
		if (status === "draft" || status === "rejected") {
			await calculateAndValidate(page);
		} else {
			await page.getByTestId("workflow-action-validate").click();
			await expect(page.getByTestId("validation-findings-panel")).toBeVisible({
				timeout: 30_000,
			});
		}
		await submitRun(page);
	}

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

test("submit with Idempotency-Key does not 404 after calculate", async ({ page }) => {
	/**
	 * FIXED: submit with Idempotency-Key previously 404'd
	 * "Payroll run not found." after a successful calculate+validate on the
	 * same run. Cause: idempotent_command commits the lease before executor,
	 * clearing SET LOCAL tenant GUCs so FOR UPDATE in _lock_run sees no row.
	 * Suspect: backend/app/services/idempotency.py + tenancy bind.
	 * Repro: calculated run → Submit (UI always sends Idempotency-Key) → error
	 * in confirm dialog.
	 *
	 * Uses a supplemental run because the period's regular run was already
	 * submitted by the previous test.
	 */
	await ensurePayrollPeriod(page);
	await createOrOpenPayRun(page, { runType: "supplemental" });
	const status = await page.getByTestId("run-status-badge").getAttribute("data-status");
	if (status === "draft" || status === "rejected") {
		await calculateAndValidate(page);
		await submitRun(page);
	} else if (status === "calculated") {
		await page.getByTestId("workflow-action-validate").click();
		await expect(page.getByTestId("validation-findings-panel")).toBeVisible({
			timeout: 30_000,
		});
		await submitRun(page);
	}
	await expect(page.getByTestId("run-status-badge")).toHaveAttribute("data-status", "submitted", {
		timeout: 30_000,
	});
});
