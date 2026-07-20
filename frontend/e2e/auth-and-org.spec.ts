import { mkdirSync } from "node:fs";

import { expect, test } from "@playwright/test";

import {
	ensureAuthenticatedLanding,
	ensureSingletonOrganization,
	loginViaDevBypass,
} from "./helpers/auth";
import { AUTH_DIR, STORAGE_STATE_PATH } from "./helpers/paths";
import { uniqueSlug, writeRunContext } from "./helpers/run-context";
import { authenticatedLanding } from "./helpers/ui";

/**
 * Setup project: reuses the singleton org (provisioned via CLI) and persists
 * storageState for dependent chromium specs. Does not create organizations via UI.
 */
test.describe.configure({ mode: "serial" });

test("dev-bypass login, reuse singleton org, land with static brand", async ({ page }) => {
	const orgSlug = uniqueSlug("e2e-org");

	await loginViaDevBypass(page);
	const orgName = await ensureSingletonOrganization(page);
	await ensureAuthenticatedLanding(page);

	await expect(authenticatedLanding(page)).toBeVisible();

	const brand = page.locator('[data-slot="sidebar-header"]').first();
	await expect(brand).toContainText(orgName);
	// No switcher menu / Add under ADR 0011.
	await expect(page.getByRole("menuitem", { name: "Add" })).toHaveCount(0);

	mkdirSync(AUTH_DIR, { recursive: true });
	writeRunContext({ orgSlug, orgName });
	await page.context().storageState({ path: STORAGE_STATE_PATH });
});
