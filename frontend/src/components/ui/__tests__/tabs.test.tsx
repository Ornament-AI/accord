import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

describe("Tabs", () => {
	it("uses primary color for the active line tab", () => {
		render(
			<Tabs value="details">
				<TabsList variant="line">
					<TabsTrigger value="details">Details</TabsTrigger>
					<TabsTrigger value="payment">Payment</TabsTrigger>
				</TabsList>
			</Tabs>,
		);

		expect(screen.getByRole("tab", { name: "Details" })).toHaveClass("data-active:text-primary");
	});
});
