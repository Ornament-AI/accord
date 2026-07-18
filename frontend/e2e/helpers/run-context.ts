import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

import { AUTH_DIR, type RunContext, RUN_CONTEXT_PATH } from "./paths";

export function uniqueSlug(prefix = "e2e"): string {
	const stamp = Date.now().toString(36);
	const rand = Math.random().toString(36).slice(2, 8);
	return `${prefix}-${stamp}-${rand}`;
}

export function writeRunContext(context: RunContext): void {
	mkdirSync(AUTH_DIR, { recursive: true });
	writeFileSync(RUN_CONTEXT_PATH, `${JSON.stringify(context, null, 2)}\n`, "utf8");
}

export function readRunContext(): RunContext {
	return JSON.parse(readFileSync(RUN_CONTEXT_PATH, "utf8")) as RunContext;
}

export function updateRunContext(patch: Partial<RunContext>): RunContext {
	const next = { ...readRunContext(), ...patch };
	writeRunContext(next);
	return next;
}
