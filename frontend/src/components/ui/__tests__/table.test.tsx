import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";

describe("Table", () => {
	it("adds scroll-aware fade to the shared table container", () => {
		render(
			<Table>
				<TableBody>
					<TableRow>
						<TableCell>Value</TableCell>
					</TableRow>
				</TableBody>
			</Table>,
		);

		const table = screen.getByRole("table");
		const scroller = table.parentElement;
		expect(scroller).toHaveClass("app-table-scroll", "scroll-fade-x", "overflow-x-auto");
		expect(scroller?.parentElement).toHaveClass("app-table-surface", "overflow-hidden");
	});
});
