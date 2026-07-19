import { expect, type Page } from "@playwright/test";

import { authenticatedLanding, clickUntilDialog } from "./ui";

/**
 * Dev auth bypass (backend DevAuthAdapter): GET /api/auth/login establishes a
 * session immediately and redirects — there is no WorkOS round-trip. Identity
 * email/name come from DEV_AUTH_EMAIL / DEV_AUTH_NAME read at backend process
 * startup, so a second UI identity is impossible without restarting uvicorn.
 *
 * Keep a defensive redirect rewrite for stacks started with an older or custom
 * localhost BASE_URL. route.fetch must not follow the redirect: fulfilling the
 * original /api/auth/login request with the final SPA response leaves the browser
 * URL on the API path and makes React Router render its catch-all page.
 */
export async function loginViaDevBypass(page: Page): Promise<void> {
	await page.route("**/api/auth/login**", async (route) => {
		const response = await route.fetch({ maxRedirects: 0 });
		const headers = { ...response.headers() };
		const location = headers.location ?? headers.Location;
		if (typeof location === "string" && location.includes("://localhost:5173")) {
			headers.location = location.replace("://localhost:5173", "://127.0.0.1:5173");
			delete headers.Location;
		}
		await route.fulfill({
			status: response.status(),
			headers,
			body: await response.body(),
		});
	});

	await page.goto("/login");
	await expect(page.getByRole("heading", { name: "Welcome" })).toBeVisible();
	await page.getByRole("button", { name: "Sign in" }).click();
	await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 30_000 });
}

/**
 * Recover the capability-aware authenticated landing page if an interrupted
 * navigation or stale retry starts on another route. Normal login, org create,
 * and org switch flows should already stay on their matched route.
 */
export async function ensureAuthenticatedLanding(page: Page): Promise<void> {
	const notFound = page.getByText("Page not found");
	if (await notFound.isVisible().catch(() => false)) {
		const home = page.getByRole("link", { name: "Return Home" });
		if (await home.isVisible().catch(() => false)) {
			await home.click();
		} else {
			await page.goto("/");
		}
	} else if (!page.url().endsWith("/") && !new URL(page.url()).pathname.endsWith("/")) {
		await page.goto("/");
	}

	if (
		!(await authenticatedLanding(page)
			.isVisible()
			.catch(() => false))
	) {
		await page.goto("/");
	}

	await expect(authenticatedLanding(page)).toBeVisible({ timeout: 30_000 });
}

export async function fillCreateOrganizationDialog(
	page: Page,
	opts: { name: string },
): Promise<void> {
	const dialog = page.getByRole("dialog");
	await expect(dialog.getByRole("heading", { name: "Create Organization" })).toBeVisible();
	await dialog.getByLabel("Name").fill(opts.name);
	await dialog.getByRole("button", { name: "Create Organization" }).click();
	await expect(dialog).toBeHidden({ timeout: 30_000 });
}

/** Create org from the inline NoOrganizationPage form. */
export async function createOrganization(page: Page, opts: { name: string }): Promise<void> {
	await expect(page.getByTestId("no-organization-page")).toBeVisible();
	await page.getByLabel("Organization Name").fill(opts.name);
	await page.getByRole("button", { name: "Continue" }).click();
}

/** Create org from NoOrganizationPage, or from the org switcher if already a member. */
export async function ensureUniqueOrganization(page: Page, opts: { name: string }): Promise<void> {
	const noOrgPage = page.getByTestId("no-organization-page");
	const landing = authenticatedLanding(page);

	// Wait for /me + React to settle before branching — a non-waiting isVisible()
	// right after login redirect races the no-org page and wrongly takes the
	// "already has org" path.
	await expect(noOrgPage.or(landing)).toBeVisible({ timeout: 30_000 });

	if (await noOrgPage.isVisible()) {
		await createOrganization(page, opts);
		await ensureAuthenticatedLanding(page);
		return;
	}

	// Already authenticated into some org (e.g. retry after a prior create).
	await ensureAuthenticatedLanding(page);
	const switcher = page.locator('[data-slot="sidebar-header"]').getByRole("button").first();
	await switcher.click();
	const createMenuItem = page.getByRole("menuitem", { name: "Add" });
	await clickUntilDialog(page, createMenuItem);
	await fillCreateOrganizationDialog(page, opts);
	await ensureAuthenticatedLanding(page);
}
