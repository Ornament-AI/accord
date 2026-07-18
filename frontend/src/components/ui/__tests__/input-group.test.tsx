import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InputGroupInput } from "@/components/ui/input-group";

describe("InputGroupInput", () => {
	it("truncates long placeholder text with an ellipsis", () => {
		render(<InputGroupInput aria-label="Filter" placeholder="Mob. Adv. Outstanding %" />);

		expect(screen.getByLabelText("Filter")).toHaveClass("truncate");
	});
});
