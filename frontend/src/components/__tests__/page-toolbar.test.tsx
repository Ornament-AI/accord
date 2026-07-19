import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PageToolbar } from "@/components/page-toolbar";

describe("PageToolbar", () => {
	it("scrolls filters while keeping trailing actions fixed", () => {
		render(
			<PageToolbar trailing={<button type="button">Add</button>}>
				<input aria-label="Filter" />
			</PageToolbar>,
		);

		const filterScroller = screen.getByLabelText("Filter").parentElement;
		expect(filterScroller).toHaveClass("min-w-0", "flex-1", "overflow-x-auto");
		expect(screen.getByRole("button", { name: "Add" }).parentElement).toHaveClass("flex-none");
	});
});
