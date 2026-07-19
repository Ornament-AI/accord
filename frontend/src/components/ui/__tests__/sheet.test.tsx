import { render } from "@testing-library/react";
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
});
