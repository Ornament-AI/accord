import { expect, type Locator, type Page } from "@playwright/test";

/** Base UI select: open trigger, pick option by accessible name. */
export async function selectByLabel(
	page: Page,
	label: string | RegExp,
	optionName: string | RegExp,
): Promise<void> {
	const trigger = page.getByRole("combobox", { name: label });
	await trigger.click();
	const option = page.getByRole("option", { name: optionName });
	await expect(option).toBeVisible();
	await option.click();
}

export async function selectWithin(
	scope: Locator,
	label: string | RegExp,
	optionName: string | RegExp,
): Promise<void> {
	const page = scope.page();
	const trigger = scope.getByRole("combobox", { name: label });
	await trigger.click();
	const option = page.getByRole("option", { name: optionName });
	await expect(option).toBeVisible();
	await option.click();
}

export async function openNav(page: Page, title: string): Promise<void> {
	const link = page.getByRole("link", { name: title });
	if (!(await link.isVisible().catch(() => false))) {
		await page.goto("/");
		await expect(page.getByTestId("dashboard-page")).toBeVisible({ timeout: 30_000 });
	}
	await link.click();
}

export function isoDate(offsetDays = 0): string {
	const d = new Date();
	d.setDate(d.getDate() + offsetDays);
	const yyyy = d.getFullYear();
	const mm = String(d.getMonth() + 1).padStart(2, "0");
	const dd = String(d.getDate()).padStart(2, "0");
	return `${yyyy}-${mm}-${dd}`;
}
