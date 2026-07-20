import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
	Pagination,
	PaginationContent,
	PaginationEllipsis,
	PaginationItem,
	PaginationLink,
	PaginationNext,
	PaginationPrevious,
} from "@/components/ui/pagination";

describe("Pagination", () => {
	it("propagates disabled state to rendered buttons", () => {
		const onPrevious = vi.fn();

		render(
			<Pagination>
				<PaginationContent>
					<PaginationItem>
						<PaginationPrevious render={<button type="button" disabled onClick={onPrevious} />} />
					</PaginationItem>
				</PaginationContent>
			</Pagination>,
		);

		const previous = screen.getByRole("button", { name: "Go to Previous Page" });
		expect(previous).toBeDisabled();

		fireEvent.click(previous);
		expect(onPrevious).not.toHaveBeenCalled();
	});

	it("calls click handlers on enabled rendered buttons", () => {
		const onNext = vi.fn();

		render(
			<Pagination>
				<PaginationContent>
					<PaginationItem>
						<PaginationNext render={<button type="button" onClick={onNext} />} />
					</PaginationItem>
				</PaginationContent>
			</Pagination>,
		);

		fireEvent.click(screen.getByRole("button", { name: "Go to Next Page" }));
		expect(onNext).toHaveBeenCalledTimes(1);
	});

	it("renders active page links and ellipsis", () => {
		render(
			<Pagination>
				<PaginationContent>
					<PaginationItem>
						<PaginationLink href="/page/2" isActive>
							2
						</PaginationLink>
					</PaginationItem>
					<PaginationItem>
						<PaginationEllipsis />
					</PaginationItem>
				</PaginationContent>
			</Pagination>,
		);

		expect(screen.getByRole("link", { name: "2" })).toHaveAttribute("aria-current", "page");
		expect(screen.getByText("More Pages")).toBeInTheDocument();
	});
});
