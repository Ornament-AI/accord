export function hasQueryValue<T>(value: T): value is Exclude<T, null | undefined | ""> {
	return value !== undefined && value !== null && value !== "";
}

export function hasPositiveQueryValue(value: unknown): boolean {
	if (!hasQueryValue(value)) return false;
	const numericValue = typeof value === "number" ? value : Number(value);
	return Number.isFinite(numericValue) && numericValue > 0;
}

export function shouldSetQueryParam(key: string, value: unknown): boolean {
	if (["bill_id", "lender_id", "page", "page_size", "spv_id"].includes(key)) {
		return hasPositiveQueryValue(value);
	}
	return hasQueryValue(value);
}

export function payloadSnippet(data: unknown): string {
	try {
		return JSON.stringify(data).slice(0, 200);
	} catch {
		return String(data).slice(0, 200);
	}
}
