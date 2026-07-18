import { fireEvent, render, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Calendar } from "@/components/ui/calendar";

function getDayButton(date: Date): HTMLButtonElement {
	const button = document.querySelector<HTMLButtonElement>(
		`button[data-day="${date.toLocaleDateString()}"]`,
	);
	expect(button).not.toBeNull();
	return button as HTMLButtonElement;
}

describe("Calendar", () => {
	it("moves DOM focus when arrow keys change the focused day", async () => {
		render(
			<Calendar
				mode="single"
				defaultMonth={new Date(2026, 0, 1)}
				selected={new Date(2026, 0, 1)}
			/>,
		);

		const january1 = getDayButton(new Date(2026, 0, 1));
		january1.focus();
		fireEvent.focus(january1);
		expect(january1).toHaveFocus();

		fireEvent.keyDown(january1, { key: "ArrowRight" });

		await waitFor(() => expect(getDayButton(new Date(2026, 0, 2))).toHaveFocus());
	});
});
