import { describe, expect, it } from "vitest";

import { organizationSlugCandidate, suggestOrganizationSlug } from "@/lib/organization-slug";

describe("suggestOrganizationSlug", () => {
	it("derives lowercase kebab-case from a display name", () => {
		expect(suggestOrganizationSlug("Acme Payroll")).toBe("acme-payroll");
		expect(suggestOrganizationSlug("  North  Star!! ")).toBe("north-star");
	});

	it("falls back for empty, short, or reserved results", () => {
		expect(suggestOrganizationSlug("!!!")).toBe("organization");
		expect(suggestOrganizationSlug("a")).toBe("organization");
		expect(suggestOrganizationSlug("API")).toBe("organization");
	});

	it("truncates to 50 characters without a trailing hyphen", () => {
		const long = "a".repeat(60);
		expect(suggestOrganizationSlug(long)).toHaveLength(50);
		expect(suggestOrganizationSlug(`${"a".repeat(40)}---${"b".repeat(20)}`).endsWith("-")).toBe(
			false,
		);
	});
});

describe("organizationSlugCandidate", () => {
	it("returns the base slug without a disambiguator", () => {
		expect(organizationSlugCandidate("Acme Payroll")).toBe("acme-payroll");
	});

	it("appends a disambiguator and stays within length bounds", () => {
		expect(organizationSlugCandidate("Acme Payroll", "ab12cd")).toBe("acme-payroll-ab12cd");
		const long = "a".repeat(60);
		const candidate = organizationSlugCandidate(long, "xyz123");
		expect(candidate).toHaveLength(50);
		expect(candidate.endsWith("-xyz123")).toBe(true);
	});
});
