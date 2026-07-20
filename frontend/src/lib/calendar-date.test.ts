import { describe, expect, it } from "vitest";

import { parseApiDate, toApiDate } from "@/lib/calendar-date";

describe("calendar-date", () => {
	it("round-trips API dates without applying a timezone", () => {
		const date = parseApiDate("2026-07-20");

		expect(date.getFullYear()).toBe(2026);
		expect(date.getMonth()).toBe(6);
		expect(date.getDate()).toBe(20);
		expect(toApiDate(date)).toBe("2026-07-20");
	});
});
