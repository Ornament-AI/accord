import { describe, expect, it } from "vitest";

import { parseContentDispositionFilename } from "@/lib/content-disposition";

describe("parseContentDispositionFilename", () => {
	it("decodes an RFC 5987 filename and prefers it over filename", () => {
		expect(
			parseContentDispositionFilename(
				"attachment; filename=report.xlsx; filename*=UTF-8''pay%20bill%20June.xlsx",
			),
		).toBe("pay bill June.xlsx");
	});

	it("parses quoted and plain filenames", () => {
		expect(parseContentDispositionFilename('attachment; filename="pay bill.xlsx"')).toBe(
			"pay bill.xlsx",
		);
		expect(parseContentDispositionFilename("attachment; filename=pay-bill.xlsx")).toBe(
			"pay-bill.xlsx",
		);
	});

	it("retains an encoded filename when percent decoding fails", () => {
		expect(
			parseContentDispositionFilename("attachment; filename*=UTF-8''invalid%E0%A4%A.xlsx"),
		).toBe("invalid%E0%A4%A.xlsx");
	});

	it("trims filenames and rejects missing or whitespace-only values", () => {
		expect(parseContentDispositionFilename("attachment; filename=  pay-bill.xlsx  ")).toBe(
			"pay-bill.xlsx",
		);
		expect(parseContentDispositionFilename('attachment; filename="   "')).toBeNull();
		expect(parseContentDispositionFilename("attachment; filename*=UTF-8''%20%20")).toBeNull();
		expect(parseContentDispositionFilename("attachment")).toBeNull();
		expect(parseContentDispositionFilename(null)).toBeNull();
	});
});
