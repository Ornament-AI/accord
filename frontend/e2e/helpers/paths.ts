import path from "node:path";
import { fileURLToPath } from "node:url";

const e2eDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

export const AUTH_DIR = path.join(e2eDir, ".auth");
export const STORAGE_STATE_PATH = path.join(AUTH_DIR, "user.json");
export const RUN_CONTEXT_PATH = path.join(AUTH_DIR, "run-context.json");

export type RunContext = {
	/** Unique slug used for this Playwright process run. */
	orgSlug: string;
	orgName: string;
	employeeNumber?: string;
	employeeName?: string;
	componentCode?: string;
	officeCode?: string;
};
