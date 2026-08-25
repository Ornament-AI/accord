import { fireEvent, screen } from "@testing-library/react";
import { vi } from "vitest";

export function mockToast() {
	return {
		toast: {
			success: vi.fn(),
			error: vi.fn(),
			info: vi.fn(),
			warning: vi.fn(),
		},
	};
}

// Base UI's Select trigger opens on pointerdown; jsdom needs both events
// to convince the underlying focus + open machinery.
export function openBaseUiSelect(trigger: HTMLElement) {
	fireEvent.pointerDown(trigger, { button: 0 });
	fireEvent.click(trigger);
}

// Base UI's onClick guards against committing unless pointerType is 'touch'
// OR the item is highlighted. Touch-typed pointer events satisfy the first
// branch — equivalent to a tap on mobile.
export function pickBaseUiOption(name: string | RegExp) {
	const option = screen.getByRole("option", { name });
	fireEvent.pointerEnter(option, { pointerType: "touch" });
	fireEvent.pointerDown(option, { pointerType: "touch", button: 0 });
	fireEvent.pointerUp(option, { pointerType: "touch", button: 0 });
	fireEvent.click(option);
}

/** Open a DatePicker by label and select an API calendar date (`YYYY-MM-DD`). */
export function pickDateByLabel(label: string | RegExp, iso: string) {
	const [year, month, day] = iso.split("-").map(Number);
	const target = new Date(year, month - 1, day);
	const dataDay = target.toLocaleDateString();
	fireEvent.click(screen.getByLabelText(label));

	const dropdowns = document.querySelectorAll<HTMLSelectElement>(
		'[data-slot="date-picker-content"] select',
	);
	if (dropdowns.length >= 2) {
		const monthSelect = dropdowns[0];
		const yearSelect = dropdowns[1];
		fireEvent.change(monthSelect, { target: { value: String(month - 1) } });
		fireEvent.change(yearSelect, { target: { value: String(year) } });
	} else {
		const targetIndex = year * 12 + (month - 1);
		const now = new Date();
		let cursorIndex = now.getFullYear() * 12 + now.getMonth();
		while (cursorIndex !== targetIndex) {
			if (cursorIndex > targetIndex) {
				fireEvent.click(screen.getByRole("button", { name: "Go to the Previous Month" }));
				cursorIndex -= 1;
			} else {
				fireEvent.click(screen.getByRole("button", { name: "Go to the Next Month" }));
				cursorIndex += 1;
			}
		}
	}

	const dayButton = document.querySelector(`[data-day="${dataDay}"]`) as HTMLElement | null;
	if (!dayButton) {
		throw new Error(`Calendar day not found for ${iso} (${dataDay})`);
	}
	fireEvent.click(dayButton);
}
