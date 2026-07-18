import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

describe("Tabs", () => {
	it("uses primary color for the active tab", () => {
		render(
			<Tabs value="details">
				<TabsList>
					<TabsTrigger value="details">Details</TabsTrigger>
					<TabsTrigger value="payment">Payment</TabsTrigger>
				</TabsList>
			</Tabs>,
		);

		expect(screen.getByRole("tablist")).toHaveAttribute("data-variant", "default");
		expect(screen.getByRole("tab", { name: "Details" })).toHaveClass(
			"data-active:bg-primary",
			"data-active:text-primary-foreground",
			"data-active:hover:text-primary-foreground",
		);
	});
});
