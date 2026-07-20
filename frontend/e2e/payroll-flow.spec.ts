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
 * Payroll runs are unique per period. The serial chain shares one monthly
 * draft (add input → calculate/validate/submit).
 */

test.describe.configure({ mode: "serial" });

function currentYearMonth(): { year: string; month: string; label: string } {
	const now = new Date();
	return {
		year: String(now.getFullYear()),
		// Current calendar month so employee versions (effective_from ≈ today) are in-range.
		month: String(now.getMonth() + 1),
		label: now.toLocaleDateString("en-US", { month: "short", year: "numeric" }),
	};
}

/** Open the current monthly payroll run, creating its period and draft when needed. */
async function createOrOpenPayRun(page: Page): Promise<void> {
	const { label } = currentYearMonth();
	await page.goto("/pay-runs");
	await expect(page.getByTestId("pay-runs-page")).toBeVisible({ timeout: 30_000 });

	const dialog = await clickUntilDialog(page, page.getByRole("button", { name: "Add" }).first());
	await expect(dialog.getByRole("heading", { name: "Add Pay Run" })).toBeVisible();
	await dialog.getByRole("button", { name: "Payroll Month" }).click();
	await page.getByRole("button", { name: label }).click();
	await dialog.getByRole("button", { name: "Continue" }).click();
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

	await createOrOpenPayRun(page);

	const status = await page.getByTestId("run-status-badge").getAttribute("data-status");
	// Retry-safe: a prior worker may have already advanced this monthly run.
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

	// Reuse the monthly draft from the add-input test (one run per period).
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
