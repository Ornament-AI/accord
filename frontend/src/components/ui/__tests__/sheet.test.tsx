import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

describe("Sheet", () => {
	it("uses the same dimmed backdrop blur as dialogs", () => {
		render(
			<Sheet open>
				<SheetContent>
					<SheetTitle>Example sheet</SheetTitle>
				</SheetContent>
			</Sheet>,
		);

		expect(document.querySelector("[data-slot='sheet-overlay']")).toHaveClass(
			"bg-black/62",
			"backdrop-blur-[3px]",
		);
	});

	it("renders the shared close control as an accessible ghost X button", () => {
		render(
			<Sheet open>
				<SheetContent>
					<SheetTitle>Example sheet</SheetTitle>
				</SheetContent>
			</Sheet>,
		);

		const closeButton = screen.getByRole("button", { name: "Close" });
		expect(closeButton).toHaveAttribute("data-variant", "ghost");
		expect(closeButton).toHaveAttribute("data-size", "icon");
		expect(closeButton).toHaveClass(
			"top-3",
			"right-3",
			"bg-transparent",
			"text-muted-foreground",
			"hover:bg-transparent",
			"dark:hover:bg-transparent",
		);
		expect(closeButton.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
		expect(closeButton.querySelector("path")?.getAttribute("d")).toContain("M208.49,191.51");
	});
});
