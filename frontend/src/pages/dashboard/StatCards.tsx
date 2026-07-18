import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { DashboardResponse } from "@/lib/api/dashboard";
import { formatCanonicalMoney } from "@/lib/api/payroll-runs";
import { cn } from "@/lib/utils";

type StatCardsProps = {
	data: DashboardResponse;
};

function regimeSubtext(byRegime: DashboardResponse["headcount"]["by_regime"]): string {
	return `GPF ${byRegime.gpf} / NPS ${byRegime.nps} / EPF ${byRegime.epf}`;
}

function deltaDirection(delta: string): "up" | "down" | "flat" {
	const trimmed = delta.trim();
	if (trimmed === "0" || trimmed === "0.0" || trimmed === "0.00" || trimmed === "-0.00") {
		return "flat";
	}
	return trimmed.startsWith("-") ? "down" : "up";
}

function VarianceIndicator({ delta, testId }: { delta: string; testId: string }) {
	const direction = deltaDirection(delta);
	const Icon = direction === "up" ? ArrowUpRight : direction === "down" ? ArrowDownRight : Minus;
	const label =
		direction === "up" ? "Up vs previous" : direction === "down" ? "Down vs previous" : "Unchanged";

	return (
		<span
			className={cn(
				"inline-flex items-center gap-1 text-xs font-medium",
				direction === "up" && "text-emerald-600 dark:text-emerald-400",
				direction === "down" && "text-rose-600 dark:text-rose-400",
				direction === "flat" && "text-muted-foreground",
			)}
			data-testid={testId}
			data-direction={direction}
			title={`${label}: ${formatCanonicalMoney(delta)}`}
		>
			<Icon className="size-3.5" aria-hidden="true" />
			<span className="sr-only">{label}</span>
			{formatCanonicalMoney(delta)}
		</span>
	);
}

export function StatCards({ data }: StatCardsProps) {
	const { headcount, latest_posted: latestPosted, variance } = data;

	return (
		<div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="dashboard-stat-cards">
			<Card size="sm" data-testid="stat-active-employees">
				<CardHeader className="border-b">
					<CardTitle className="text-sm font-medium text-muted-foreground">
						Active employees
					</CardTitle>
				</CardHeader>
				<CardContent className="flex flex-col gap-1">
					<p className="text-2xl font-semibold tracking-tight">{headcount.active_employees}</p>
					<p className="text-xs text-muted-foreground">{regimeSubtext(headcount.by_regime)}</p>
				</CardContent>
			</Card>

			<Card size="sm" data-testid="stat-latest-gross">
				<CardHeader className="border-b">
					<CardTitle className="text-sm font-medium text-muted-foreground">
						Latest posted gross
					</CardTitle>
				</CardHeader>
				<CardContent className="flex flex-col gap-1">
					<p className="text-2xl font-semibold tracking-tight">
						{formatCanonicalMoney(latestPosted?.totals.gross)}
					</p>
					{variance ? (
						<VarianceIndicator delta={variance.gross_delta} testId="variance-gross" />
					) : null}
				</CardContent>
			</Card>

			<Card size="sm" data-testid="stat-net-payable">
				<CardHeader className="border-b">
					<CardTitle className="text-sm font-medium text-muted-foreground">Net payable</CardTitle>
				</CardHeader>
				<CardContent className="flex flex-col gap-1">
					<p className="text-2xl font-semibold tracking-tight">
						{formatCanonicalMoney(latestPosted?.totals.net)}
					</p>
					{variance ? <VarianceIndicator delta={variance.net_delta} testId="variance-net" /> : null}
				</CardContent>
			</Card>

			<Card size="sm" data-testid="stat-employer-cost">
				<CardHeader className="border-b">
					<CardTitle className="text-sm font-medium text-muted-foreground">Employer cost</CardTitle>
				</CardHeader>
				<CardContent className="flex flex-col gap-1">
					<p className="text-2xl font-semibold tracking-tight">
						{formatCanonicalMoney(latestPosted?.totals.employer_contribution)}
					</p>
				</CardContent>
			</Card>
		</div>
	);
}
