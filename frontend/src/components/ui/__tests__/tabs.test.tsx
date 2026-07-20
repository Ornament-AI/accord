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
			"group-data-[variant=default]/tabs-list:data-active:bg-primary",
			"group-data-[variant=default]/tabs-list:data-active:text-primary-foreground",
			"group-data-[variant=default]/tabs-list:data-active:hover:text-primary-foreground",
		);
	});

	it("uses primary-text for the active line-tab label", () => {
		render(
			<Tabs value="details">
				<div className="overflow-x-auto border-b">
					<TabsList variant="line">
						<TabsTrigger value="details">Details</TabsTrigger>
						<TabsTrigger value="payment">Payment</TabsTrigger>
					</TabsList>
				</div>
			</Tabs>,
		);

		const detailsTab = screen.getByRole("tab", { name: "Details" });
		expect(detailsTab).toHaveClass(
			"group-data-[variant=line]/tabs-list:data-active:text-primary-text",
			"group-data-[variant=line]/tabs-list:data-active:hover:text-primary-text",
			"group-data-horizontal/tabs:after:bottom-0",
			"group-data-[variant=line]/tabs-list:data-active:after:opacity-100",
		);
		expect(detailsTab).not.toHaveClass(
			"data-active:text-primary-foreground",
			"group-data-horizontal/tabs:after:bottom-[-5px]",
		);
	});
});
