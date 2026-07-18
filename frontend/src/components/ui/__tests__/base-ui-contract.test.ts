import { describe, expect, it } from "vitest";

import config from "../../../../components.json";
import packageJson from "../../../../package.json";

describe("Base UI contract", () => {
	it("keeps shadcn and dependencies pointed at Base UI", () => {
		const dependencies = {
			...packageJson.dependencies,
			...packageJson.devDependencies,
		};

		expect(config.style).toMatch(/^base-/);
		expect(dependencies["@base-ui/react"]).toBeTruthy();
		expect(Object.keys(dependencies).filter((name) => name.startsWith("@radix-ui/"))).toEqual([]);
	});
});
