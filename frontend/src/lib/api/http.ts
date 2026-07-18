import { resolveApiUrl } from "@/lib/api-url";
import { parseContentDispositionFilename } from "@/lib/content-disposition";
import { ApiError } from "@/lib/errors";

export type DownloadResult = { blob: Blob; filename: string };

type HeaderMap = Record<string, string>;

function appendHeaders(target: HeaderMap, source: HeadersInit | undefined): void {
	if (!source) return;

	if (typeof Headers !== "undefined" && source instanceof Headers) {
		source.forEach((value, key) => {
			target[key] = value;
		});
		return;
	}

	if (Array.isArray(source)) {
		for (const [key, value] of source) {
			target[key] = value;
		}
		return;
	}

	for (const [key, value] of Object.entries(source)) {
		target[key] = String(value);
	}
}

function mergeRequestHeaders(initHeaders: HeadersInit | undefined): HeaderMap {
	const headers: HeaderMap = {};
	appendHeaders(headers, initHeaders);
	return headers;
}

function extractErrorDetail(errorBody: unknown, statusCode: number): string {
	if (typeof errorBody === "object" && errorBody && "detail" in errorBody) {
		const detail = (errorBody as Record<string, unknown>).detail;
		return formatErrorDetail(detail) ?? `Request failed with status ${statusCode}`;
	}
	return `Request failed with status ${statusCode}`;
}

function formatErrorDetail(detail: unknown): string | null {
	if (typeof detail === "string") return detail;
	if (typeof detail === "number" || typeof detail === "boolean") return String(detail);
	if (Array.isArray(detail)) {
		const messages = detail
			.map(formatValidationIssue)
			.filter((message): message is string => Boolean(message));
		return messages.length > 0 ? messages.join("; ") : null;
	}
	if (typeof detail === "object" && detail) {
		if ("message" in detail && typeof detail.message === "string") return detail.message;
		if ("msg" in detail && typeof detail.msg === "string") return detail.msg;
		try {
			return JSON.stringify(detail);
		} catch {
			return null;
		}
	}
	return null;
}

function formatValidationIssue(issue: unknown): string | null {
	if (typeof issue === "string") return issue;
	if (typeof issue !== "object" || !issue) return formatErrorDetail(issue);
	const record = issue as Record<string, unknown>;
	const message =
		typeof record.msg === "string"
			? record.msg
			: typeof record.message === "string"
				? record.message
				: null;
	if (!message) return formatErrorDetail(issue);
	const loc = Array.isArray(record.loc)
		? record.loc.filter((part) => part !== "body").join(".")
		: "";
	return loc ? `${loc}: ${message}` : message;
}

async function readErrorBody(response: Response): Promise<{ json: unknown; text: string | null }> {
	const text = await response.text().catch(() => "");
	if (!text) {
		return { json: null, text: null };
	}
	try {
		return { json: JSON.parse(text) as unknown, text };
	} catch {
		return { json: null, text };
	}
}

function textErrorDetail(text: string | null, statusCode: number): string {
	if (!text) {
		return `Request failed with status ${statusCode}`;
	}
	const compact = text.replace(/\s+/g, " ").trim();
	const snippet = compact.length > 160 ? `${compact.slice(0, 157)}...` : compact;
	return `Request failed with status ${statusCode}: ${snippet}`;
}

function buildAuthReturnUrl(): string {
	const loc = window.location;
	const returnTo = loc.pathname + loc.search + loc.hash;
	return `/login?returnTo=${encodeURIComponent(returnTo)}`;
}

export function extractErrorCode(errorBody: unknown): string | null {
	if (typeof errorBody === "object" && errorBody && "error" in errorBody) {
		return String((errorBody as Record<string, unknown>).error);
	}
	return null;
}

function resetAuthSession(message: string): never {
	sessionStorage.setItem("auth_error", message);
	window.location.href = buildAuthReturnUrl();
	// Hang until navigation completes — avoids React Query onError toasts.
	return new Promise<never>(() => {}) as never;
}

export async function fetchWithAuth(url: string, init?: RequestInit): Promise<Response> {
	let response: Response;
	try {
		const { credentials = "include", headers, ...rest } = init ?? {};
		response = await fetch(resolveApiUrl(url), {
			...rest,
			credentials,
			headers: mergeRequestHeaders(headers),
		});
	} catch (error) {
		throw new ApiError("Unable to reach the server. Check your connection.", 0, {
			detail: error instanceof Error ? error.message : "Network error",
		});
	}
	if (!response.ok) {
		const errorBody = await readErrorBody(response);
		const errorCode = extractErrorCode(errorBody.json);
		if (response.status === 401) {
			const message =
				errorCode === "InvalidToken"
					? "Your session expired. Please sign in again."
					: "Please sign in to continue.";
			return resetAuthSession(message);
		}
		const detail =
			errorBody.json === null
				? textErrorDetail(errorBody.text, response.status)
				: extractErrorDetail(errorBody.json, response.status);
		throw new ApiError(detail, response.status, { detail, code: errorCode ?? undefined });
	}
	return response;
}

export async function fetchJson<T>(input: string, init?: RequestInit): Promise<T> {
	const response = await fetchWithAuth(input, init);
	const text = await response.text();
	const trimmed = text.trim();
	if (!trimmed) return undefined as T;
	return JSON.parse(trimmed) as T;
}

export async function fetchVoid(input: string, init?: RequestInit): Promise<void> {
	await fetchWithAuth(input, init);
}

export async function fetchBlob(input: string, init?: RequestInit): Promise<Blob> {
	const response = await fetchWithAuth(input, init);
	return response.blob();
}

export async function fetchBlobWithHeaders(
	input: string,
	init?: RequestInit,
): Promise<{ blob: Blob; headers: Headers }> {
	const response = await fetchWithAuth(input, init);
	return { blob: await response.blob(), headers: response.headers };
}

export async function fetchDownload(
	input: string,
	init?: RequestInit,
	fallbackFilename = "download",
): Promise<DownloadResult> {
	const { blob, headers } = await fetchBlobWithHeaders(input, init);
	const parsed = parseContentDispositionFilename(headers.get("content-disposition"));
	return { blob, filename: parsed ?? fallbackFilename };
}
