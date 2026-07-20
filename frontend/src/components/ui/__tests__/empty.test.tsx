import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Empty, EmptyMedia } from "@/components/ui/empty";

describe("Empty", () => {
	it("uses the shared outlined treatment by default", () => {
		const { container } = render(<Empty />);

		expect(container.firstChild).toHaveClass(
			"h-full",
			"w-full",
			"flex-1",
			"border",
			"border-border",
		);
	});

	it("lets callers opt into a dashed border", () => {
		const { container } = render(<Empty className="border border-dashed" />);

		expect(container.firstChild).toHaveClass("border", "border-dashed");
	});

	it("renders icon media without a colored fill or tile", () => {
		const { container } = render(<EmptyMedia variant="icon" />);

		expect(container.firstChild).toHaveClass("size-6");
		expect(container.firstChild).not.toHaveClass("bg-muted", "text-icon-accent", "rounded-lg");
	});
});
