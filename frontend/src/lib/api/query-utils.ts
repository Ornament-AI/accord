export type QueryParamValue = string | number | boolean | null | undefined;

export function hasQueryValue<T>(value: T): value is Exclude<T, null | undefined | ""> {
	return value !== undefined && value !== null && value !== "";
}

function hasPositiveQueryValue(value: unknown): boolean {
	if (!hasQueryValue(value)) return false;
	const numericValue = typeof value === "number" ? value : Number(value);
	return Number.isFinite(numericValue) && numericValue > 0;
}

/** Pagination params are only meaningful when positive; everything else just needs a value. */
export function shouldSetQueryParam(key: string, value: unknown): boolean {
	if (key === "page" || key === "page_size") {
		return hasPositiveQueryValue(value);
	}
	return hasQueryValue(value);
}

/**
 * Serialize params into a `?key=value` query string, skipping empty values.
 *
 * The default predicate also skips `false` (boolean flags are only sent when
 * set). Pass `shouldSetQueryParam` to keep `false` values and apply the
 * positive-only pagination rule instead.
 */
export function buildQueryString(
	params: Record<string, QueryParamValue>,
	shouldSet: (key: string, value: QueryParamValue) => boolean = (_key, value) =>
		hasQueryValue(value) && value !== false,
): string {
	const search = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (!shouldSet(key, value)) continue;
		search.set(key, String(value));
	}
	const qs = search.toString();
	return qs ? `?${qs}` : "";
}
