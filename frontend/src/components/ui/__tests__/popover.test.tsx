import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

describe("PopoverContent", () => {
	it("puts the portaled positioner in a foreground stacking layer", () => {
		render(
			<Popover open>
				<PopoverTrigger>Open reports date filter</PopoverTrigger>
				<PopoverContent>Reports date filter calendar</PopoverContent>
			</Popover>,
		);

		expect(screen.getByText("Reports date filter calendar")).toBeInTheDocument();
		expect(document.querySelector("[data-slot='popover-positioner']")).toHaveClass(
			"isolate",
			"z-50",
		);
	});
});
