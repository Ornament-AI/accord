import { ApiError } from "@/lib/errors";

/**
 * Parse FastAPI-style validation detail strings produced by fetchJson
 * (e.g. "locale: Invalid locale; currency: …") into field → message map.
 */
export function parseFieldErrors(error: unknown): Record<string, string> {
	if (!(error instanceof ApiError)) return {};
	const source = error.detail || error.message;
	const fields: Record<string, string> = {};
	for (const part of source.split("; ")) {
		const separator = part.indexOf(": ");
		if (separator <= 0) continue;
		const loc = part.slice(0, separator).trim();
		const message = part.slice(separator + 2).trim();
		if (!loc || !message) continue;
		const key =
			loc
				.split(".")
				.filter((segment) => segment !== "body")
				.pop() ?? loc;
		fields[key] = message;
	}
	return fields;
}
