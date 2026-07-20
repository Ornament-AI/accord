import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogTitle } from "@/components/ui/dialog";

describe("Dialog", () => {
	it("renders the shared close control as an accessible ghost icon button", () => {
		render(
			<Dialog open>
				<DialogContent>
					<DialogTitle>Example dialog</DialogTitle>
				</DialogContent>
			</Dialog>,
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
		expect(closeButton.querySelector("path")?.getAttribute("d")).toContain("M208.49,191.51");
	});

	it("distributes footer actions evenly on mobile and restores desktop alignment", () => {
		render(
			<DialogFooter data-testid="dialog-footer">
				<Button variant="outline">Cancel</Button>
				<Button>Create</Button>
			</DialogFooter>,
		);

		const footer = screen.getByTestId("dialog-footer");
		expect(footer).toHaveClass(
			"flex-nowrap",
			"justify-center",
			"[&>button]:h-auto",
			"[&>button]:min-h-9",
			"[&>button]:flex-1",
			"[&>button]:whitespace-normal",
			"sm:justify-end",
			"sm:[&>button]:h-9",
			"sm:[&>button]:flex-none",
			"sm:[&>button]:whitespace-nowrap",
		);
	});
});
