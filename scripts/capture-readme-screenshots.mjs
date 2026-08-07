/**
 * Capture product screenshots for README.md into docs/images/.
 * Prerequisites: local stack running, provisioned org, seeded June fixture.
 *
 * Usage (from repo root):
 *   node scripts/capture-readme-screenshots.mjs
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const require = createRequire(import.meta.url);
const { chromium } = require(
	path.join(root, "node_modules/.pnpm/playwright@1.61.1/node_modules/playwright"),
);
const outDir = path.join(root, "docs", "images");
const baseURL = process.env.FRONTEND_URL ?? "http://127.0.0.1:5173";

async function shot(page, name) {
	await page.waitForTimeout(400);
	await page.screenshot({ path: path.join(outDir, name), animations: "disabled" });
	console.log(`  wrote ${name}`);
}

/** Best-effort JPEG for the heavy login grain background (macOS `sips`). */
async function compressLoginJpeg() {
	const { spawnSync } = await import("node:child_process");
	const png = path.join(outDir, "login.png");
	const jpg = path.join(outDir, "login.jpg");
	const result = spawnSync(
		"sips",
		["-s", "format", "jpeg", "-s", "formatOptions", "82", png, "--out", jpg],
		{ encoding: "utf8" },
	);
	if (result.status === 0) {
		console.log("  wrote login.jpg (compressed)");
	} else {
		console.warn("  could not compress login.jpg; keep login.png for README");
	}
}

async function forceLightTheme(page) {
	await page.addInitScript(() => {
		localStorage.setItem("ACCORD_THEME", "light");
	});
}

async function login(page) {
	await page.goto(`${baseURL}/login`);
	await page.getByRole("heading", { name: "Welcome" }).waitFor({ timeout: 30_000 });
	await page.getByLabel("Email").fill("dev@accord.local");
	await page.getByLabel("Password").fill("dev");
	await shot(page, "login.png");
	await page.getByRole("button", { name: "Sign in" }).click();
	await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 30_000 });
}

async function ensureJunePayRunCalculated(page) {
	await page.goto(`${baseURL}/pay-runs`);
	await page.getByTestId("pay-runs-page").waitFor({ timeout: 30_000 });

	const juneRow = page.locator("table tbody tr", { hasText: /June 2026/i });
	if (await juneRow.count()) {
		await juneRow.first().click();
	} else {
		await page.getByRole("button", { name: "Add" }).first().click();
		const dialog = page.getByRole("dialog");
		await dialog.getByRole("heading", { name: "Add Pay Run" }).waitFor();
		await dialog.getByRole("button", { name: "Payroll Month" }).click();
		const june = page.getByRole("button", { name: /Jun 2026|June 2026/i });
		if (await june.isVisible().catch(() => false)) {
			await june.click();
		} else {
			// Month picker may list "June 2026" as a calendar cell / option.
			await page.getByText(/June 2026|Jun 2026/i).first().click();
		}
		await dialog.getByRole("button", { name: "Continue" }).click();
	}

	await page.getByTestId("pay-run-detail-page").waitFor({ timeout: 30_000 });
	const status = await page.getByTestId("run-status-badge").getAttribute("data-status");
	if (status !== "draft") {
		return;
	}

	const editBtn = page.getByRole("button", { name: /^Edit$/i });
	if (await editBtn.isVisible().catch(() => false)) {
		await editBtn.click();
	}

	const selectAll = page.getByRole("checkbox", { name: /Select All Employees|Clear Selection/i });
	await selectAll.waitFor({ timeout: 30_000 });
	const checked = await selectAll.isChecked().catch(() => false);
	if (!checked) {
		await selectAll.click();
	}

	const saveBtn = page.getByRole("button", { name: /^Save$/i });
	if (await saveBtn.isVisible().catch(() => false)) {
		await saveBtn.click();
		await page.waitForTimeout(1500);
	}

	const calc = page.getByRole("button", { name: /Calculate/i }).first();
	await calc.waitFor({ timeout: 30_000 });
	for (let i = 0; i < 20 && (await calc.isDisabled()); i++) {
		await page.waitForTimeout(500);
	}
	if (await calc.isDisabled()) {
		console.warn("  calculate still disabled; capturing draft run");
		return;
	}
	await calc.click();
	await page.getByTestId("pay-run-totals").waitFor({ timeout: 120_000 });
}

async function main() {
	await mkdir(outDir, { recursive: true });
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({
		viewport: { width: 1440, height: 900 },
		deviceScaleFactor: 1,
		colorScheme: "light",
	});
	const page = await context.newPage();
	await forceLightTheme(page);

	console.log("login…");
	await login(page);

	console.log("employees…");
	await page.goto(`${baseURL}/employees`);
	await page.getByTestId("employee-list-page").waitFor({ timeout: 30_000 });
	await page.getByText("E001").first().waitFor({ timeout: 30_000 });
	await shot(page, "employees.png");

	console.log("employee detail…");
	await page.locator("table tbody tr").first().click();
	await page.getByTestId("employee-detail-page").waitFor({ timeout: 30_000 });
	await shot(page, "employee-detail.png");

	console.log("pay runs list…");
	await page.goto(`${baseURL}/pay-runs`);
	await page.getByTestId("pay-runs-page").waitFor({ timeout: 30_000 });
	await shot(page, "pay-runs.png");

	console.log("pay run detail…");
	try {
		await ensureJunePayRunCalculated(page);
	} catch (err) {
		console.warn(`  pay-run prep skipped: ${err.message ?? err}`);
		await page.goto(`${baseURL}/pay-runs`);
		await page.getByTestId("pay-runs-page").waitFor({ timeout: 30_000 });
		const row = page.locator("table tbody tr").first();
		if (await row.isVisible().catch(() => false)) {
			await row.click();
			await page.getByTestId("pay-run-detail-page").waitFor({ timeout: 30_000 });
		}
	}
	await shot(page, "pay-run-detail.png");

	console.log("reports…");
	await page.goto(`${baseURL}/reports/pay-bill`);
	await page.getByTestId("reports-page").waitFor({ timeout: 30_000 });
	await shot(page, "reports.png");

	console.log("audit…");
	await page.goto(`${baseURL}/audit`);
	await page.getByTestId("audit-page").waitFor({ timeout: 30_000 });
	await shot(page, "audit.png");

	await compressLoginJpeg();
	await browser.close();
	console.log(`Done → ${outDir}`);
}

main().catch((err) => {
	console.error(err);
	process.exit(1);
});
