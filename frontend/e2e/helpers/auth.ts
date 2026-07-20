import { expect, type Page } from "@playwright/test";

import { authenticatedLanding } from "./ui";

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
 * navigation or stale retry starts on another route.
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

/**
 * Ensure the singleton org is available for e2e.
 *
 * Normal path: reuse an already-active membership (access_state=active).
 * If the deployment is unbootstrapped, fail with instructions to run
 * `scripts/provision_organization.py` (no UI create path under ADR 0011).
 * Multi-org legacy DBs must be reset with `scripts/reset_e2e_db.sh`.
 */
export async function ensureSingletonOrganization(page: Page): Promise<string> {
	const notReady = page.getByTestId("deployment-not-ready-page");
	const notProvisioned = page.getByTestId("not-provisioned-page");
	const landing = authenticatedLanding(page);

	await expect(notReady.or(notProvisioned).or(landing)).toBeVisible({ timeout: 30_000 });

	if (await notReady.isVisible()) {
		throw new Error(
			"Deployment is unbootstrapped. Run migrations, then: " +
				"backend/.venv/bin/python scripts/provision_organization.py " +
				"--name 'E2E Org' --slug e2e-org --admin-email \"$DEV_AUTH_EMAIL\". " +
				"For a dirty multi-org e2e DB: scripts/reset_e2e_db.sh --i-understand-this-deletes-data",
		);
	}

	if (await notProvisioned.isVisible()) {
		throw new Error(
			"Dev auth user is not a member of the singleton org. " +
				"Run: backend/.venv/bin/python scripts/provision_member.py " +
				"--email \"$DEV_AUTH_EMAIL\" --role organization_administrator",
		);
	}

	await ensureAuthenticatedLanding(page);
	const brand = page.locator('[data-slot="sidebar-header"]').first();
	const name = (await brand.innerText()).split("\n")[0]?.trim() ?? "Organization";
	return name;
}

/** @deprecated Use ensureSingletonOrganization — kept as alias for older specs. */
export async function ensureUniqueOrganization(
	page: Page,
	_opts?: { name: string },
): Promise<void> {
	await ensureSingletonOrganization(page);
}
