/** Canonical money string: non-negative digits with at most 2 decimal places. */
const CANONICAL_MONEY_RE = /^(0|[1-9]\d*)(\.\d{1,2})?$/;

export function isCanonicalMoneyString(value: string): boolean {
	return CANONICAL_MONEY_RE.test(value);
}

/** Parse a canonical money string to a number for comparisons. */
export function parseMoneyString(value: string): number | null {
	if (!isCanonicalMoneyString(value)) return null;
	const num = Number(value);
	return Number.isFinite(num) ? num : null;
}

export function validatePositiveMoney(value: string, label: string): string | null {
	const trimmed = value.trim();
	if (!trimmed) return `${label} is required.`;
	if (!isCanonicalMoneyString(trimmed)) {
		return `${label} must be a valid money amount (up to 2 decimal places).`;
	}
	const amount = parseMoneyString(trimmed);
	if (amount === null || amount <= 0) {
		return `${label} must be greater than zero.`;
	}
	return null;
}

export function validateNonNegativeMoney(value: string, label: string): string | null {
	const trimmed = value.trim();
	if (!trimmed) return `${label} is required.`;
	if (!isCanonicalMoneyString(trimmed)) {
		return `${label} must be a valid money amount (up to 2 decimal places).`;
	}
	return null;
}
