import { describe, expect, it } from "vitest";

import { sanitizeReturnTo } from "@/lib/return-to";

describe("sanitizeReturnTo", () => {
	it("allows in-app relative paths", () => {
		expect(sanitizeReturnTo("/")).toBe("/");
		expect(sanitizeReturnTo("/employees")).toBe("/employees");
		expect(sanitizeReturnTo("/reports?tab=1")).toBe("/reports?tab=1");
	});

	it("rejects open redirects", () => {
		expect(sanitizeReturnTo("//evil.example")).toBe("/");
		expect(sanitizeReturnTo("https://evil.example")).toBe("/");
		expect(sanitizeReturnTo("http://evil.example/path")).toBe("/");
		expect(sanitizeReturnTo(null)).toBe("/");
	});
});
