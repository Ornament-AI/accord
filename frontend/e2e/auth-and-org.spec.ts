import { mkdirSync } from "node:fs";

import { expect, test } from "@playwright/test";

import {
	ensureDashboard,
	ensureUniqueOrganization,
	loginViaDevBypass,
} from "./helpers/auth";
import { AUTH_DIR, STORAGE_STATE_PATH } from "./helpers/paths";
import { uniqueSlug, writeRunContext } from "./helpers/run-context";

/**
 * Setup project: establishes the single-run org and persists storageState for
 * dependent chromium specs. Fresh slug every process so re-runs on accord_e2e
 * do not collide.
 */
test.describe.configure({ mode: "serial" });

test("dev-bypass login, create org, land on dashboard with switcher", async ({ page }) => {
	const orgSlug = uniqueSlug("e2e-org");
	const orgName = `E2E Org ${orgSlug}`;

	await loginViaDevBypass(page);
	await ensureUniqueOrganization(page, { name: orgName });
	await ensureDashboard(page);

	await expect(page.getByTestId("dashboard-page")).toBeVisible();

	// Org switcher trigger shows the active organization name.
	const switcher = page.locator('[data-slot="sidebar-header"]').getByRole("button").first();
	await expect(switcher).toContainText(orgName);
	await switcher.click();
	await expect(page.getByRole("menuitem", { name: orgName })).toBeVisible();
	await expect(page.getByRole("menuitem", { name: "Create organization" })).toBeVisible();
	await page.keyboard.press("Escape");

	mkdirSync(AUTH_DIR, { recursive: true });
	writeRunContext({ orgSlug, orgName });
	await page.context().storageState({ path: STORAGE_STATE_PATH });
});
