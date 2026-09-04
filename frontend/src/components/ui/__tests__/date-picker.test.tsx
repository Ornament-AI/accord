import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DatePicker } from "@/components/ui/date-picker";

describe("DatePicker", () => {
	it("shows a concise placeholder when no date is selected", () => {
		render(<DatePicker />);

		expect(screen.getByRole("button")).toHaveTextContent("Date");
	});

	it("formats the selected date in the trigger", () => {
		render(<DatePicker value={new Date(2026, 4, 7)} />);

		expect(screen.getByRole("button")).toHaveTextContent("07 May, 2026");
	});
});
