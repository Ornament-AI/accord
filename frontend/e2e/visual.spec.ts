import { existsSync } from "node:fs";

import { expect, type TestInfo, test } from "@playwright/test";

import { ensureAuthenticatedLanding } from "./helpers/auth";

/**
 * Minimal visual-regression surface (release gate K).
 *
 * No baselines are committed yet — each test skips with a clear message when
 * its expected PNG is absent and snapshots are not being regenerated
 * (`updateSnapshots` "none"/"missing"). Generate baselines deliberately on
 * the evidence machine with
 *   pnpm --filter frontend exec playwright test e2e/visual.spec.ts --update-snapshots
 * and commit `visual.spec.ts-snapshots/`. Baselines are platform- and
 * data-sensitive; screenshots clip to the viewport with a small diff
 * tolerance for sub-pixel font rendering variance.
 */

const SHOT_OPTS = {
	fullPage: false,
	maxDiffPixelRatio: 0.02,
	animations: "disabled" as const,
};

// `all` regenerates every baseline; `changed` only updates existing ones.
const UPDATING_MODES = new Set(["all", "changed"]);

function skipWithoutBaseline(testInfo: TestInfo, name: string): void {
	if (UPDATING_MODES.has(testInfo.config.updateSnapshots)) {
		return;
	}
	test.skip(
		!existsSync(testInfo.snapshotPath(name, { kind: "screenshot" })),
		`visual baseline ${name} is not committed yet — generate it on the evidence machine (see e2e/README.md)`,
	);
}

test.describe("visual regression", () => {
	test("authenticated landing", async ({ page }, testInfo) => {
		skipWithoutBaseline(testInfo, "landing.png");
		await ensureAuthenticatedLanding(page);
		await expect(page).toHaveScreenshot("landing.png", SHOT_OPTS);
	});

	test("pay runs list", async ({ page }, testInfo) => {
		skipWithoutBaseline(testInfo, "pay-runs.png");
		await page.goto("/pay-runs");
		await expect(page.getByTestId("pay-runs-page")).toBeVisible({ timeout: 30_000 });
		await expect(page).toHaveScreenshot("pay-runs.png", SHOT_OPTS);
	});

	test("pay run detail", async ({ page }, testInfo) => {
		skipWithoutBaseline(testInfo, "pay-run-detail.png");
		await page.goto("/pay-runs");
		const runRow = page.locator("table tbody tr").first();
		await expect(runRow).toBeVisible({ timeout: 30_000 });
		await runRow.click();
		await expect(page.getByTestId("pay-run-detail-page")).toBeVisible({ timeout: 30_000 });
		await expect(page).toHaveScreenshot("pay-run-detail.png", SHOT_OPTS);
	});
});
