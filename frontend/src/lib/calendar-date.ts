/** Format a local Date as an API calendar date (`YYYY-MM-DD`). */
export function toApiDate(date: Date): string {
	const year = date.getFullYear();
	const month = String(date.getMonth() + 1).padStart(2, "0");
	const day = String(date.getDate()).padStart(2, "0");
	return `${year}-${month}-${day}`;
}

/** Parse an API calendar date (`YYYY-MM-DD`) without applying a timezone. */
export function parseApiDate(value: string): Date {
	const [year, month, day] = value.split("-").map(Number);
	return new Date(year, month - 1, day);
}

export function todayApiDate(): string {
	return toApiDate(new Date());
}
