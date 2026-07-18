import { defineConfig, devices } from "@playwright/test";

/**
 * Critical-path browser E2E against the manually started local stack.
 * Start/stop and env commands: see e2e/README.md (webServer is not managed here).
 */
export default defineConfig({
	testDir: "./e2e",
	fullyParallel: false,
	forbidOnly: !!process.env.CI,
	retries: 1,
	workers: 1,
	timeout: 90_000,
	expect: { timeout: 15_000 },
	reporter: [["list"], ["html", { open: "never", outputFolder: "e2e/playwright-report" }]],
	outputDir: "e2e/test-results",
	use: {
		baseURL: "http://127.0.0.1:5173",
		trace: "on-first-retry",
		screenshot: "only-on-failure",
	},
	projects: [
		{
			name: "setup",
			testMatch: /auth-and-org\.spec\.ts/,
		},
		{
			name: "chromium",
			use: {
				...devices["Desktop Chrome"],
				storageState: "e2e/.auth/user.json",
			},
			dependencies: ["setup"],
			testIgnore: /auth-and-org\.spec\.ts/,
		},
	],
});
