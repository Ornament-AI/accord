import { expect, type Page, test } from "@playwright/test";

import { E2E_CHECKER_EMAIL, loginAsEmail, logoutViaApi } from "./helpers/auth";
import { readRunContext } from "./helpers/run-context";
import { openNav } from "./helpers/ui";

/**
 * Full maker/checker journey: admin submits, a second provisioned identity
 * (E2E_CHECKER_EMAIL, organization_administrator) approves and posts, then
 * the export → poll → download journey runs against the real stack.
 *
 * Requires a one-time member provision (see e2e/README.md):
 *   backend/.venv/bin/python scripts/provision_member.py \
 *     --email e2e.checker@accord.local --role organization_administrator
 */

test.describe.configure({ mode: "serial" });

async function openNewestPayRun(page: Page): Promise<void> {
	await page.goto("/pay-runs");
	await expect(page.getByTestId("pay-runs-page")).toBeVisible({ timeout: 30_000 });
	const runRow = page.locator("table tbody tr").first();
	await expect(runRow).toBeVisible({ timeout: 30_000 });
	await runRow.click();
	await expect(page.getByTestId("pay-run-detail-page")).toBeVisible({ timeout: 30_000 });
}

async function confirmWorkflowAction(page: Page, action: string): Promise<void> {
	await page.getByTestId(`workflow-action-${action}`).click();
	const confirm = page.getByTestId("workflow-confirm-dialog");
	await expect(confirm).toBeVisible();
	await confirm.getByTestId("workflow-confirm-submit").click();
	await expect(confirm).toBeHidden({ timeout: 30_000 });
}

async function runStatus(page: Page): Promise<string> {
	const badge = page.getByTestId("run-status-badge");
	return (await badge.getAttribute("data-status")) ?? "";
}

test.describe("reports", () => {
	test("maker/checker approve → post → export → download journey", async ({ page }) => {
		const ctx = readRunContext();
		expect(ctx.employeeNumber, "master-data.spec must create an employee first").toBeTruthy();

		// Drive the monthly run to submitted as the admin (maker).
		await openNewestPayRun(page);
		let status = await runStatus(page);
		if (status === "draft" || status === "calculated") {
			if (status === "draft") {
				await page.getByRole("button", { name: "Calculate Pay Run" }).click();
				await expect(page.getByTestId("pay-run-totals")).toBeVisible({ timeout: 60_000 });
			}
			await confirmWorkflowAction(page, "submit");
			// The badge refetch races the mutation's invalidateQueries — wait
			// for submitted rather than reading a possibly-stale status once.
			await expect(page.getByTestId("run-status-badge")).toHaveAttribute(
				"data-status",
				"submitted",
				{ timeout: 30_000 },
			);
			status = "submitted";
		}
		if (status !== "submitted" && status !== "approved" && status !== "posted") {
			throw new Error(`run could not be driven to submitted (status=${status})`);
		}

		// Checker identity approves and posts — maker/checker demands a distinct
		// subject, which the dev adapter derives from the submitted email.
		if (status === "submitted") {
			await logoutViaApi(page);
			await loginAsEmail(page, E2E_CHECKER_EMAIL);
			await openNewestPayRun(page);
			await confirmWorkflowAction(page, "approve");
			await expect(page.getByTestId("run-status-badge")).toHaveAttribute(
				"data-status",
				"approved",
				{ timeout: 30_000 },
			);
			status = "approved";
		}

		if (status === "approved") {
			await openNewestPayRun(page);
			await confirmWorkflowAction(page, "post");
			await expect(page.getByTestId("run-status-badge")).toHaveAttribute("data-status", "posted", {
				timeout: 30_000,
			});
		}

		// Reports: select the posted run, export the workbook, download the artifact.
		await openNav(page, "Reports");
		await expect(page.getByTestId("reports-page")).toBeVisible({ timeout: 30_000 });
		const runSelect = page.getByLabel("Select Posted Run");
		await expect(runSelect).toBeVisible({ timeout: 30_000 });
		await runSelect.click();
		await page.getByRole("option").first().click();

		await page.getByRole("button", { name: /Export/ }).click();
		const artifactRow = page.getByTestId("artifacts-section").locator("table tbody tr").first();
		await expect(artifactRow).toBeVisible({ timeout: 120_000 });

		const downloadPromise = page.waitForEvent("download", { timeout: 60_000 });
		await artifactRow.getByRole("button", { name: /Download artifact/ }).click();
		const download = await downloadPromise;
		expect(download.suggestedFilename()).toMatch(/\.xlsx$/);
	});

	test("reports page shows empty posted-run state without a posted run", async ({ page }) => {
		// Runs only when no posted run exists yet; otherwise the selector shows.
		await page.goto("/reports");
		await expect(page.getByTestId("reports-page")).toBeVisible({ timeout: 30_000 });
		if (
			await page
				.getByLabel("Select Posted Run")
				.isVisible()
				.catch(() => false)
		) {
			test.skip(true, "a posted run already exists in this database");
			return;
		}
		await expect(page.getByText("No Posted Runs Yet")).toBeVisible();
	});
});
