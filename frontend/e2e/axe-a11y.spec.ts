import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { authenticatedLanding } from "./helpers/ui";

type AxeViolation = {
	id: string;
	impact?: string | null;
	description: string;
	nodes: Array<{ target: string[] }>;
};

async function runAxe(page: Page, label: string): Promise<void> {
	const results = await new AxeBuilder({ page }).analyze();
	const violations = results.violations as AxeViolation[];

	const seriousOrCritical = violations.filter(
		(v) => v.impact === "serious" || v.impact === "critical",
	);
	const moderate = violations.filter((v) => v.impact === "moderate");

	if (moderate.length > 0) {
		const summary = moderate.map((v) => `${v.id} (${v.impact}): ${v.description}`).join("\n  - ");
		console.warn(`[axe:${label}] moderate violations (documented, non-failing):\n  - ${summary}`);
	}

	expect(
		seriousOrCritical,
		`[axe:${label}] serious/critical violations:\n${JSON.stringify(seriousOrCritical, null, 2)}`,
	).toEqual([]);
}

test.describe("axe a11y smoke", () => {
	test("login page has no serious/critical violations", async ({ browser }) => {
		// Fresh context without storageState so /login is reachable.
		const context = await browser.newContext({ storageState: undefined });
		const page = await context.newPage();
		await page.goto("/login");
		await expect(page.getByRole("heading", { name: "Welcome" })).toBeVisible();
		await runAxe(page, "login");
		await context.close();
	});

	test("authenticated landing has no serious/critical violations", async ({ page }) => {
		await page.goto("/");
		await expect(authenticatedLanding(page)).toBeVisible({ timeout: 30_000 });
		await runAxe(page, "authenticated-landing");
	});

	test("employees list has no serious/critical violations", async ({ page }) => {
		await page.goto("/employees");
		await expect(page.getByTestId("employee-list-page")).toBeVisible({ timeout: 30_000 });
		await runAxe(page, "employees");
	});
});
