import { expect, test } from "@playwright/test";

import { ensureAuthenticatedLanding } from "./helpers/auth";

/**
 * Minimal visual-regression surface (release gate K).
 *
 * Baselines live next to this spec (visual.spec.ts-snapshots/) and are
 * platform-sensitive: regenerate deliberately on the evidence machine with
 *   pnpm --filter frontend exec playwright test e2e/visual.spec.ts --update-snapshots
 * and commit the updated PNGs. Screenshots clip to the viewport with a small
 * diff tolerance for sub-pixel font rendering variance.
 */

const SHOT_OPTS = {
	fullPage: false,
	maxDiffPixelRatio: 0.02,
	animations: "disabled" as const,
};

test.describe("visual regression", () => {
	test("authenticated landing", async ({ page }) => {
		await ensureAuthenticatedLanding(page);
		await expect(page).toHaveScreenshot("landing.png", SHOT_OPTS);
	});

	test("pay runs list", async ({ page }) => {
		await page.goto("/pay-runs");
		await expect(page.getByTestId("pay-runs-page")).toBeVisible({ timeout: 30_000 });
		await expect(page).toHaveScreenshot("pay-runs.png", SHOT_OPTS);
	});

	test("pay run detail", async ({ page }) => {
		await page.goto("/pay-runs");
		const runRow = page.locator("table tbody tr").first();
		await expect(runRow).toBeVisible({ timeout: 30_000 });
		await runRow.click();
		await expect(page.getByTestId("pay-run-detail-page")).toBeVisible({ timeout: 30_000 });
		await expect(page).toHaveScreenshot("pay-run-detail.png", SHOT_OPTS);
	});
});
