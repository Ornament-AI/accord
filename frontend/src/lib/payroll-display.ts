/** Display formatting for payroll runs (labels and canonical money strings). */

export function periodLabel(year: number, month: number): string {
	return new Date(year, month - 1).toLocaleDateString("en-US", {
		month: "long",
		year: "numeric",
	});
}

export function inputKindLabel(value: string): string {
	return value
		.split("_")
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

export function statusLabel(value: string): string {
	return value
		.split("_")
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

/**
 * Format a canonical money string for display without parseFloat.
 * Accepts optional leading sign and up to 2 decimal places.
 */
export function formatCanonicalMoney(value: string | null | undefined): string {
	if (value == null || value === "") return "—";
	const trimmed = value.trim();
	const match = trimmed.match(/^(-?)(\d+)(?:\.(\d{1,2}))?$/);
	if (!match) return trimmed;

	const sign = match[1];
	const intPart = match[2];
	const frac = (match[3] ?? "00").padEnd(2, "0");

	let grouped = intPart;
	if (intPart.length > 3) {
		const last3 = intPart.slice(-3);
		let rest = intPart.slice(0, -3);
		const parts: string[] = [];
		while (rest.length > 2) {
			parts.unshift(rest.slice(-2));
			rest = rest.slice(0, -2);
		}
		if (rest) parts.unshift(rest);
		grouped = `${parts.join(",")},${last3}`;
	}

	return `\u20B9${sign}${grouped}.${frac}`;
}
