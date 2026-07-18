import { describe, expect, it } from "vitest";

import { formatDate } from "./utils";

describe("formatDate", () => {
	it("keeps API calendar dates on the stated day", () => {
		expect(formatDate("2026-06-01")).toBe("01 Jun, 2026");
		expect(formatDate("1990-01-01")).toBe("01 Jan, 1990");
	});

	it("rejects impossible calendar dates", () => {
		expect(formatDate("2026-02-30")).toBe("-");
	});
});
