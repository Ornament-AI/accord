import { describe, expect, it } from "vitest";

import { buttonVariants } from "@/components/ui/button-variants";

describe("buttonVariants", () => {
	it("keeps primary text contrast intact on hover", () => {
		const classes = buttonVariants({ variant: "default" });

		expect(classes).toContain("hover:bg-primary");
		expect(classes).not.toContain("hover:bg-primary/");
		expect(classes).toContain("accord-motion-interactive");
		expect(classes).toContain("accord-motion-pressable");
	});

	it("skips press scale on link buttons", () => {
		expect(buttonVariants({ variant: "link" })).not.toContain("accord-motion-pressable");
	});

	it("uses the semantic foreground for destructive buttons", () => {
		expect(buttonVariants({ variant: "destructive" })).toContain("text-destructive-foreground");
	});
});
