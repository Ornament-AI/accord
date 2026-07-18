import { describe, expect, it } from "vitest";

import * as ChartExports from "@/components/ui/lazy-recharts";

describe("lazy-recharts", () => {
	it("exports deferred Recharts wrappers", () => {
		const forwardRefType = Symbol.for("react.forward_ref");
		const components = [
			ChartExports.Bar,
			ChartExports.BarChart,
			ChartExports.CartesianGrid,
			ChartExports.Label,
			ChartExports.Legend,
			ChartExports.Pie,
			ChartExports.PieChart,
			ChartExports.Rectangle,
			ChartExports.ResponsiveContainer,
			ChartExports.Sector,
			ChartExports.Tooltip,
			ChartExports.XAxis,
			ChartExports.YAxis,
		];

		for (const component of components) {
			expect((component as { $$typeof?: symbol }).$$typeof).toBe(forwardRefType);
			expect((component as { displayName?: string }).displayName).toMatch(/^LazyRecharts\./);
		}
	});
});
