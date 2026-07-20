import { expect, test } from "@playwright/test";

import { openNav } from "./helpers/ui";

test.describe("reports", () => {
	test("generate-report journey requires a posted run (skipped under single dev-auth identity)", async ({
		page,
	}) => {
		/**
		 * SKIP REASON (dev-auth limitation):
		 * Report generation requires a posted payroll run. Posting needs Approve
		 * by a different identity than the submitter (maker/checker). DevAuthAdapter
		 * binds a single identity (DEV_AUTH_EMAIL) for the life of the backend
		 * process, so a second reviewer cannot sign in via the UI without restarting
		 * uvicorn with a different DEV_AUTH_EMAIL. Therefore a posted run is not
		 * achievable through the public UI in this E2E lane; the generate → poll →
		 * download journey is skipped. See e2e/README.md.
		 */
		test.skip(
			true,
			"Posted run unreachable via UI: single DevAuthAdapter identity blocks maker/checker approve; cannot reach report generation without a second identity or backend restart.",
		);

		await openNav(page, "Reports");
		await expect(page.getByTestId("reports-page")).toBeVisible();
	});

	test("reports page shows empty posted-run state without a posted run", async ({ page }) => {
		await page.goto("/reports");
		await expect(page.getByTestId("reports-page")).toBeVisible({ timeout: 30_000 });
		await expect(page.getByText("No Posted Runs Yet")).toBeVisible();
	});
});
