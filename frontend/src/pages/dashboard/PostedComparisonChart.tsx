import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
	type ChartConfig,
	ChartContainer,
	ChartLegend,
	ChartLegendContent,
	ChartTooltip,
	ChartTooltipContent,
} from "@/components/ui/chart";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "@/components/ui/lazy-recharts";
import type { DashboardPostedRun } from "@/lib/api/dashboard";
import { formatCanonicalMoney, periodLabel } from "@/lib/api/payroll-runs";

type PostedComparisonChartProps = {
	latest: DashboardPostedRun;
	previous: DashboardPostedRun | null;
};

const chartConfig = {
	latest: {
		label: "Latest posted",
		color: "var(--chart-1)",
	},
	previous: {
		label: "Previous posted",
		color: "var(--chart-2)",
	},
} satisfies ChartConfig;

/** Convert a canonical money string to a finite number for chart scales. */
function moneyToNumber(value: string): number {
	const trimmed = value.trim();
	const match = trimmed.match(/^(-?)(\d+)(?:\.(\d{1,2}))?$/);
	if (!match) return Number.NaN;
	const sign = match[1] === "-" ? -1 : 1;
	const intPart = match[2];
	const frac = (match[3] ?? "00").padEnd(2, "0");
	return sign * (Number(intPart) + Number(frac) / 100);
}

export function PostedComparisonChart({ latest, previous }: PostedComparisonChartProps) {
	const latestLabel = periodLabel(latest.period.year, latest.period.month);
	const previousLabel = previous
		? periodLabel(previous.period.year, previous.period.month)
		: "Previous";

	const rows = [
		{
			metric: "Gross",
			latest: moneyToNumber(latest.totals.gross),
			previous: previous ? moneyToNumber(previous.totals.gross) : 0,
			latestRaw: latest.totals.gross,
			previousRaw: previous?.totals.gross ?? null,
		},
		{
			metric: "Deductions",
			latest: moneyToNumber(latest.totals.deductions),
			previous: previous ? moneyToNumber(previous.totals.deductions) : 0,
			latestRaw: latest.totals.deductions,
			previousRaw: previous?.totals.deductions ?? null,
		},
		{
			metric: "Net",
			latest: moneyToNumber(latest.totals.net),
			previous: previous ? moneyToNumber(previous.totals.net) : 0,
			latestRaw: latest.totals.net,
			previousRaw: previous?.totals.net ?? null,
		},
	];

	return (
		<Card data-testid="posted-comparison-chart">
			<CardHeader className="border-b">
				<CardTitle className="text-sm font-medium">Posted run comparison</CardTitle>
				<CardDescription>
					{previous
						? `${latestLabel} vs ${previousLabel} — gross, deductions, and net`
						: `${latestLabel} — gross, deductions, and net`}
				</CardDescription>
			</CardHeader>
			<CardContent className="pt-4">
				<ChartContainer config={chartConfig} className="aspect-auto h-64 w-full">
					<BarChart data={rows} accessibilityLayer>
						<CartesianGrid vertical={false} />
						<XAxis dataKey="metric" tickLine={false} axisLine={false} tickMargin={8} />
						<YAxis
							tickLine={false}
							axisLine={false}
							width={72}
							tickFormatter={(value: number) => formatCanonicalMoney(String(value))}
						/>
						<ChartTooltip
							content={
								<ChartTooltipContent
									formatter={(value, name) => {
										const numeric = typeof value === "number" ? value : Number(value);
										const label =
											name === "previous" ? previousLabel : name === "latest" ? latestLabel : name;
										return (
											<span className="flex w-full items-center justify-between gap-4">
												<span className="text-muted-foreground">{label}</span>
												<span className="font-mono font-medium tabular-nums">
													{Number.isFinite(numeric)
														? formatCanonicalMoney(numeric.toFixed(2))
														: "—"}
												</span>
											</span>
										);
									}}
								/>
							}
						/>
						<ChartLegend content={<ChartLegendContent />} />
						<Bar dataKey="latest" fill="var(--color-latest)" radius={4} />
						{previous ? <Bar dataKey="previous" fill="var(--color-previous)" radius={4} /> : null}
					</BarChart>
				</ChartContainer>
			</CardContent>
		</Card>
	);
}
