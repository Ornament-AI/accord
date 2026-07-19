import { expect, test } from "@playwright/test";

import { readRunContext, updateRunContext } from "./helpers/run-context";
import { authenticatedLanding, isoDate, openNav, pickDateWithin, selectWithin } from "./helpers/ui";

test.describe.configure({ mode: "serial" });

test("create office, pay component, employee; schedule pay change; PAN masked", async ({
	page,
}) => {
	const ctx = readRunContext();
	const suffix = ctx.orgSlug.slice(-8);
	const officeCode = `OFF-${suffix}`.slice(0, 32);
	const officeName = `Office ${suffix}`;
	const componentCode = `OT-${suffix}`
		.replace(/[^A-Z0-9_-]/gi, "")
		.toUpperCase()
		.slice(0, 32);
	const componentName = `Overtime ${suffix}`;
	const employeeNumber = `E-${suffix}`;
	const employeeName = `Employee ${suffix}`;
	const pan = "ABCDE1234F";

	// --- Office ---
	await page.goto("/");
	await expect(authenticatedLanding(page)).toBeVisible({ timeout: 30_000 });
	await page.goto("/organization/offices");
	await expect(page.getByTestId("offices-page")).toBeVisible({ timeout: 30_000 });
	await page.getByRole("button", { name: /^Add$/i }).click();

	const officeDialog = page.getByRole("dialog");
	await expect(officeDialog.getByRole("heading", { name: "Add Office" })).toBeVisible();
	await officeDialog.getByLabel("Code").fill(officeCode);
	await officeDialog.getByLabel("Name").fill(officeName);
	await selectWithin(officeDialog, "Jurisdiction", "Mumbai");
	await officeDialog.getByRole("button", { name: "Create office" }).click();
	await expect(officeDialog).toBeHidden({ timeout: 30_000 });
	await expect(page.getByTestId("offices-tab")).toContainText(officeCode);
	await expect(page.getByTestId("offices-tab")).toContainText(officeName);

	// --- Pay component ---
	await openNav(page, "Pay Components");
	await expect(page.getByTestId("pay-components-page")).toBeVisible();
	await page.getByRole("button", { name: "New Pay Component" }).first().click();

	const pcDialog = page.getByRole("dialog");
	await expect(pcDialog.getByRole("heading", { name: "New Pay Component" })).toBeVisible();
	await pcDialog.getByLabel("Code").fill(componentCode);
	await pcDialog.getByLabel("Name").fill(componentName);
	await selectWithin(pcDialog, "Classification", "Earning");
	await pcDialog.getByRole("button", { name: "Create component" }).click();
	await expect(pcDialog).toBeHidden({ timeout: 30_000 });
	await expect(page.getByTestId("pay-components-page")).toContainText(componentName);

	// --- Employee (composite dialog incl. retirement / tax regime) ---
	await openNav(page, "Employees");
	await expect(page.getByTestId("employee-list-page")).toBeVisible();
	await page.getByRole("button", { name: "New Employee" }).first().click();

	const empDialog = page.getByRole("dialog");
	await expect(empDialog.getByRole("heading", { name: "New Employee" })).toBeVisible();
	await empDialog.getByLabel("Employee Number").fill(employeeNumber);
	await empDialog.getByLabel("Name", { exact: true }).fill(employeeName);
	await empDialog.getByLabel("Sevarth ID").fill(`SEV-${suffix}`);
	await selectWithin(empDialog, "Retirement Regime", "NPS");
	await pickDateWithin(empDialog, "Date of Birth", "1990-05-15");
	await pickDateWithin(empDialog, "Date of Joining", "2018-01-01");
	await empDialog.getByLabel("PAN").fill(pan);

	// Optional Pay section — needed so we can schedule a subsequent pay change.
	await empDialog.getByRole("button", { name: "Pay" }).click();
	await empDialog.getByLabel("Pay Matrix Level").fill("L10");
	await empDialog.getByLabel("Basic Pay").fill("50000.00");

	await empDialog.getByRole("button", { name: "Create employee" }).click();
	await expect(page.getByTestId("employee-detail-page")).toBeVisible({ timeout: 30_000 });
	await expect(page.getByTestId("employee-detail-page")).toContainText(employeeNumber);
	await expect(page.getByTestId("employee-detail-page")).toContainText(employeeName);

	// PAN is masked by default (•••• + last 4).
	await expect(page.getByText("••••234F")).toBeVisible();
	await expect(page.getByText(pan)).toHaveCount(0);

	// Schedule a pay version change (tomorrow to avoid overlap with today's version).
	await page.getByRole("tab", { name: "Pay" }).click();
	await page.getByRole("button", { name: "Edit" }).click();
	const scheduleDialog = page.getByRole("dialog");
	await expect(scheduleDialog.getByRole("heading", { name: /Schedule pay change/i })).toBeVisible();
	await pickDateWithin(scheduleDialog, "Effective From", isoDate(1));
	await scheduleDialog.getByLabel("Pay Matrix Level").fill("L11");
	await scheduleDialog.getByLabel("Basic Pay").fill("55000.00");
	await scheduleDialog.getByRole("button", { name: "Submit" }).click();
	await expect(scheduleDialog).toBeHidden({ timeout: 30_000 });

	// Listed on employees index.
	await openNav(page, "Employees");
	await expect(page.getByTestId("employee-list-page")).toContainText(employeeNumber);
	await expect(page.getByTestId("employee-list-page")).toContainText(employeeName);

	updateRunContext({
		officeCode,
		componentCode,
		employeeNumber,
		employeeName,
	});
});
