import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

describe("overlay positioners", () => {
	it("keeps dropdown menus above sticky page content", async () => {
		render(
			<DropdownMenu open>
				<DropdownMenuTrigger>Open data sections</DropdownMenuTrigger>
				<DropdownMenuContent>
					<DropdownMenuItem>Funding Received</DropdownMenuItem>
				</DropdownMenuContent>
			</DropdownMenu>,
		);

		expect(await screen.findByRole("menuitem", { name: "Funding Received" })).toBeInTheDocument();
		expect(document.querySelector("[data-slot='dropdown-menu-positioner']")).toHaveClass(
			"isolate",
			"z-50",
		);
	});

	it("keeps collapsed-sidebar tooltips above sticky page content", () => {
		render(
			<Tooltip open>
				<TooltipTrigger>FMS</TooltipTrigger>
				<TooltipContent>FMS</TooltipContent>
			</Tooltip>,
		);

		expect(document.querySelector("[data-slot='tooltip-content']")).toHaveTextContent("FMS");
		expect(document.querySelector("[data-slot='tooltip-positioner']")).toHaveClass(
			"isolate",
			"z-50",
		);
	});
});
