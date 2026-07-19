import { describe, expect, it } from "vitest";

import { buttonVariants } from "@/components/ui/button-variants";

describe("buttonVariants", () => {
	it("keeps primary text contrast intact on hover", () => {
		const classes = buttonVariants({ variant: "default" });

		expect(classes).toContain("hover:bg-primary");
		expect(classes).not.toContain("hover:bg-primary/");
	});
});
