import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DateRangePicker } from "@/components/ui/date-range-picker";

describe("DateRangePicker", () => {
	it("uses a compact day/month/year range label", () => {
		render(
			<DateRangePicker
				value={{
					from: new Date(2026, 0, 1),
					to: new Date(2026, 4, 7),
				}}
			/>,
		);

		expect(screen.getByRole("button")).toHaveTextContent("01/01/26 - 07/05/26");
	});

	it("shows end-only ranges from URL-backed filters", () => {
		render(
			<DateRangePicker
				value={{ from: undefined, to: new Date(2026, 4, 7) }}
				placeholder="Paid dates"
			/>,
		);

		expect(screen.getByRole("button")).toHaveTextContent("Until 07/05/26");
		expect(screen.getByRole("button")).not.toHaveTextContent("Paid dates");
	});

	it("allows callers to content-fit the trigger width", () => {
		render(<DateRangePicker style={{ width: "calc(17ch)" }} />);

		expect(screen.getByRole("button").style.width).toBe("calc(17ch)");
	});

	it("does not apply the default width when callers provide a width class", () => {
		render(<DateRangePicker className="w-full" />);

		expect(screen.getByRole("button")).toHaveClass("w-full");
		expect(screen.getByRole("button")).not.toHaveClass("w-[280px]");
	});

	it("keeps the default width when callers provide only max-width constraints", () => {
		render(<DateRangePicker className="max-w-full" />);

		expect(screen.getByRole("button")).toHaveClass("w-[280px]", "max-w-full");
	});

	it("keeps caller-provided date formatting overrides", () => {
		render(
			<DateRangePicker
				value={{
					from: new Date(2026, 0, 1),
					to: new Date(2026, 4, 7),
				}}
				formatDate={(date) => date.getFullYear().toString()}
			/>,
		);

		expect(screen.getByRole("button")).toHaveTextContent("2026 - 2026");
	});
});
