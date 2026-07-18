import { describe, expect, it, vi } from "vitest";

import { createOrganizationFromName } from "@/lib/create-organization";
import { ApiError } from "@/lib/errors";

describe("createOrganizationFromName", () => {
	it("rejects an empty name", async () => {
		const create = vi.fn();
		await expect(createOrganizationFromName(create, "   ")).rejects.toThrow("Name is required.");
		expect(create).not.toHaveBeenCalled();
	});

	it("creates with a generated slug", async () => {
		const create = vi.fn().mockResolvedValue({});
		await createOrganizationFromName(create, "North Star");
		expect(create).toHaveBeenCalledWith({ name: "North Star", slug: "north-star" });
	});

	it("retries with a disambiguator after a slug conflict", async () => {
		const create = vi
			.fn()
			.mockRejectedValueOnce(new ApiError("taken", 409, { code: "Conflict" }))
			.mockResolvedValueOnce({});

		await createOrganizationFromName(create, "Taken Org");

		expect(create).toHaveBeenCalledTimes(2);
		expect(create.mock.calls[0]?.[0]).toEqual({ name: "Taken Org", slug: "taken-org" });
		expect(create.mock.calls[1]?.[0].slug).toMatch(/^taken-org-[a-z0-9]{6}$/);
	});
});
