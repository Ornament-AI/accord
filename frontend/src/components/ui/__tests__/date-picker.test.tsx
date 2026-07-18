import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DatePicker } from "@/components/ui/date-picker";

describe("DatePicker", () => {
	it("uses concise placeholder text and the shared field surface", () => {
		render(<DatePicker />);

		expect(screen.getByRole("button")).toHaveTextContent("Date");
		expect(screen.getByRole("button")).toHaveClass(
			"bg-transparent",
			"dark:bg-input/22",
			"dark:hover:bg-input/38",
			"min-w-0",
		);
		expect(screen.getByText("Date")).toHaveClass("truncate");
	});

	it("keeps selected date labels compact inside the trigger", () => {
		render(<DatePicker value={new Date(2026, 4, 7)} />);

		expect(screen.getByRole("button")).toHaveTextContent("07 May, 2026");
		expect(screen.getByText("07 May, 2026")).toHaveClass("truncate", "tabular-nums");
	});
});
