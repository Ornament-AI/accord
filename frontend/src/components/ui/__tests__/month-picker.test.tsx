import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MonthPicker } from "@/components/ui/month-picker";

describe("MonthPicker", () => {
	it("uses the same trigger surface color as toolbar controls", () => {
		render(<MonthPicker value="" onChange={vi.fn()} />);

		expect(screen.getByRole("button")).toHaveClass(
			"bg-transparent",
			"dark:bg-input/22",
			"dark:hover:bg-input/38",
			"min-w-0",
		);
	});

	it("keeps month labels compact inside the trigger", () => {
		render(<MonthPicker value="2026-05" onChange={vi.fn()} />);

		expect(screen.getByRole("button")).toHaveTextContent("May 2026");
		expect(screen.getByText("May 2026")).toHaveClass("truncate");
	});

	it("allows callers to content-fit the trigger width", () => {
		render(<MonthPicker value="" onChange={vi.fn()} style={{ width: "calc(17ch)" }} />);

		expect(screen.getByRole("button")).toHaveStyle({ width: "calc(17ch)" });
	});

	it("does not apply the default width when callers provide a width class", () => {
		render(<MonthPicker value="" onChange={vi.fn()} className="sm:w-fit" />);

		expect(screen.getByRole("button")).toHaveClass("sm:w-fit");
		expect(screen.getByRole("button")).not.toHaveClass("w-[160px]");
	});

	it("keeps the default width when callers provide only min-width constraints", () => {
		render(<MonthPicker value="" onChange={vi.fn()} className="min-w-40" />);

		expect(screen.getByRole("button")).toHaveClass("w-[160px]", "min-w-40");
	});

	it("disables months outside availableMonths and bounds year navigation", () => {
		render(
			<MonthPicker value="2026-05" onChange={vi.fn()} availableMonths={["2026-05", "2025-12"]} />,
		);

		fireEvent.click(screen.getByRole("button", { name: /May 2026|Select month/i }));
		const content = document.querySelector('[data-slot="month-picker-content"]');
		expect(content).toBeInstanceOf(HTMLElement);
		const picker = within(content as HTMLElement);

		expect(picker.getByRole("button", { name: "May 2026" })).toBeEnabled();
		expect(picker.getByRole("button", { name: "Apr 2026" })).toBeDisabled();
		expect(picker.getByRole("button", { name: "Previous Year" })).toBeEnabled();
		expect(picker.getByRole("button", { name: "Next Year" })).toBeDisabled();

		fireEvent.click(picker.getByRole("button", { name: "Previous Year" }));
		expect(picker.getByText("2025")).toBeInTheDocument();
		expect(picker.getByRole("button", { name: "Dec 2025" })).toBeEnabled();
		expect(picker.getByRole("button", { name: "Jan 2025" })).toBeDisabled();
		expect(picker.getByRole("button", { name: "Previous Year" })).toBeDisabled();
	});

	it("treats an empty availableMonths list as no selectable months", () => {
		render(<MonthPicker value="" onChange={vi.fn()} availableMonths={[]} />);

		fireEvent.click(screen.getByRole("button"));
		const content = document.querySelector('[data-slot="month-picker-content"]');
		expect(content).toBeInstanceOf(HTMLElement);
		const picker = within(content as HTMLElement);

		expect(picker.getByRole("button", { name: "Jan 2026" })).toBeDisabled();
		expect(picker.getByRole("button", { name: "Previous Year" })).toBeDisabled();
		expect(picker.getByRole("button", { name: "Next Year" })).toBeDisabled();
	});
});
