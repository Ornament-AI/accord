import { expect, type Locator, type Page } from "@playwright/test";

/** Any capability-aware page the authenticated index route can choose. */
export function authenticatedLanding(page: Page): Locator {
	return page.locator(
		'main [data-testid="pay-runs-page"], main [data-testid="employee-list-page"], main [data-testid="reports-page"], main [data-testid="audit-page"]',
	);
}

/**
 * Click a trigger until a Base UI dialog portal is visible.
 * Retries briefly — the first click can land before React handlers attach.
 */
export async function clickUntilDialog(page: Page, trigger: Locator): Promise<Locator> {
	const dialog = page.getByRole("dialog");
	await expect(trigger).toBeVisible({ timeout: 30_000 });

	for (let attempt = 0; attempt < 3; attempt++) {
		await trigger.click();
		try {
			await expect(dialog).toBeVisible({ timeout: 2_000 });
			return dialog;
		} catch {
			// retry
		}
	}

	await expect(dialog).toBeVisible({ timeout: 5_000 });
	return dialog;
}

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
	const target = page
		.getByRole("link", { name: title })
		.or(page.getByRole("menuitem", { name: title }));

	if (!(await target.first().isVisible().catch(() => false))) {
		await page.goto("/");
		await expect(authenticatedLanding(page)).toBeVisible({ timeout: 30_000 });
	}

	// Nested items live under Organization / Reports (expanded collapsible or compact flyout).
	if (!(await target.first().isVisible().catch(() => false))) {
		for (const folderName of [/^Organization$/i, /^Reports$/i]) {
			const folder = page.getByRole("button", { name: folderName });
			if (await folder.isVisible().catch(() => false)) {
				await folder.click();
			}
		}
	}

	await expect(target.first()).toBeVisible({ timeout: 10_000 });
	await target.first().click();
}

export function isoDate(offsetDays = 0): string {
	const d = new Date();
	d.setDate(d.getDate() + offsetDays);
	const yyyy = d.getFullYear();
	const mm = String(d.getMonth() + 1).padStart(2, "0");
	const dd = String(d.getDate()).padStart(2, "0");
	return `${yyyy}-${mm}-${dd}`;
}

/** Open a DatePicker by label and select an API calendar date (`YYYY-MM-DD`). */
export async function pickDateWithin(
	scope: Locator,
	label: string | RegExp,
	iso: string,
): Promise<void> {
	const page = scope.page();
	const [year, month, day] = iso.split("-").map(Number);
	const target = new Date(year, month - 1, day);
	const dataDay = target.toLocaleDateString();
	await scope.getByLabel(label).click();

	const content = page.locator('[data-slot="date-picker-content"]');
	const dropdowns = content.locator("select");
	if ((await dropdowns.count()) >= 2) {
		await dropdowns.nth(0).selectOption(String(month - 1));
		await dropdowns.nth(1).selectOption(String(year));
	} else {
		const targetIndex = year * 12 + (month - 1);
		const now = new Date();
		let cursorIndex = now.getFullYear() * 12 + now.getMonth();
		while (cursorIndex !== targetIndex) {
			if (cursorIndex > targetIndex) {
				await page.getByRole("button", { name: "Go to the Previous Month" }).click();
				cursorIndex -= 1;
			} else {
				await page.getByRole("button", { name: "Go to the Next Month" }).click();
				cursorIndex += 1;
			}
		}
	}

	await page.locator(`[data-day="${dataDay}"]`).click();
}
