/** User-facing labels: prefer human names; keep stable IDs when ambiguity matters. */

export function namedEntityLabel(
	item: { name?: string | null; code?: string | null } | null | undefined,
	fallback = "—",
): string {
	const name = item?.name?.trim();
	const code = item?.code?.trim();
	if (name && code) return `${name} (${code})`;
	if (name) return name;
	return code || fallback;
}

/** Posts use designation as the human-readable name. */
export function postEntityLabel(
	item: { designation?: string | null } | null | undefined,
	fallback = "—",
): string {
	const name = item?.designation?.trim();
	return name || fallback;
}

/** Name plus employee number when both exist — numbers are tenant-unique. */
export function employeeEntityLabel(
	item: { name?: string | null; employee_number?: string | null } | null | undefined,
	fallback = "—",
): string {
	const name = item?.name?.trim();
	const number = item?.employee_number?.trim();
	if (name && number) return `${name} (${number})`;
	if (name) return name;
	return number || fallback;
}

/** Name plus component code when both exist — codes are unique, names are not. */
export function payComponentEntityLabel(
	item: { name?: string | null; code?: string | null } | null | undefined,
	fallback = "—",
): string {
	return namedEntityLabel(item, fallback);
}
