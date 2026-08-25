import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchDownload } from "@/lib/api/http";

afterEach(() => {
	vi.unstubAllGlobals();
});

describe("fetchDownload", () => {
	it("returns the response blob and parsed Content-Disposition filename", async () => {
		const fetchMock = vi.fn().mockResolvedValue(
			new Response("report body", {
				status: 200,
				headers: {
					"Content-Disposition": "attachment; filename*=UTF-8''pay%20bill.xlsx",
					"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
				},
			}),
		);
		vi.stubGlobal("fetch", fetchMock);

		const result = await fetchDownload("/api/artifacts/artifact-1/download", undefined, "report");

		expect(result.filename).toBe("pay bill.xlsx");
		expect(await result.blob.text()).toBe("report body");
		expect(fetchMock).toHaveBeenCalledWith("/api/artifacts/artifact-1/download", {
			credentials: "include",
			headers: {},
		});
	});

	it("uses the supplied fallback when the response has no usable filename", async () => {
		const fetchMock = vi.fn().mockResolvedValue(
			new Response("report body", {
				status: 200,
				headers: { "Content-Disposition": 'attachment; filename="   "' },
			}),
		);
		vi.stubGlobal("fetch", fetchMock);

		const result = await fetchDownload(
			"/api/artifacts/artifact-2/download",
			undefined,
			"fallback.xlsx",
		);

		expect(result.filename).toBe("fallback.xlsx");
	});
});
