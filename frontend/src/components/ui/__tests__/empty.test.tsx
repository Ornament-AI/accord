import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Empty } from "@/components/ui/empty";

describe("Empty", () => {
	it("does not force a visible border by default", () => {
		const { container } = render(<Empty />);

		expect(container.firstChild).not.toHaveClass("border");
	});

	it("lets callers opt into a dashed border", () => {
		const { container } = render(<Empty className="border border-dashed" />);

		expect(container.firstChild).toHaveClass("border", "border-dashed");
	});
});
