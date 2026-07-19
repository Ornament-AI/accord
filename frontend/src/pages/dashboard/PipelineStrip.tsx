import { Link } from "react-router";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { DashboardPipeline, DashboardResponse } from "@/lib/api/dashboard";
import { periodLabel, statusLabel } from "@/lib/api/payroll-runs";

const PIPELINE_STATUSES: Array<{ key: keyof DashboardPipeline; label: string }> = [
	{ key: "draft", label: "Draft" },
	{ key: "calculated", label: "Calculated" },
	{ key: "submitted", label: "Submitted" },
	{ key: "approved", label: "Approved" },
	{ key: "posted", label: "Posted" },
	{ key: "rejected", label: "Rejected" },
	{ key: "reversed", label: "Reversed" },
];

type PipelineStripProps = {
	data: DashboardResponse;
};

export function PipelineStrip({ data }: PipelineStripProps) {
	const { pipeline, current_period: currentPeriod } = data;

	return (
		<div
			className="grid gap-3 lg:grid-cols-[1fr_minmax(14rem,20rem)]"
			data-testid="dashboard-pipeline"
		>
			<Card size="sm">
				<CardHeader className="border-b">
					<CardTitle className="text-sm font-medium">Pipeline</CardTitle>
				</CardHeader>
				<CardContent>
					<div className="flex flex-wrap gap-2" data-testid="pipeline-status-counts">
						{PIPELINE_STATUSES.map(({ key, label }) => (
							<Badge
								key={key}
								variant="secondary"
								className="gap-1.5 px-2.5 py-1 font-normal"
								data-testid={`pipeline-${key}`}
							>
								<span className="text-muted-foreground">{label}</span>
								<span className="font-semibold tabular-nums">{pipeline[key]}</span>
							</Badge>
						))}
					</div>
				</CardContent>
			</Card>

			<Card size="sm" data-testid="current-period-card">
				<CardHeader className="border-b">
					<CardTitle className="text-sm font-medium">Current Period</CardTitle>
				</CardHeader>
				<CardContent className="flex flex-col gap-2">
					{currentPeriod ? (
						<>
							<p className="text-lg font-semibold tracking-tight">
								{periodLabel(currentPeriod.year, currentPeriod.month)}
							</p>
							{currentPeriod.run ? (
								<div className="flex flex-wrap items-center gap-2">
									<Badge variant="outline" data-testid="current-period-run-status">
										{statusLabel(currentPeriod.run.status)}
									</Badge>
									{currentPeriod.run.version_number != null ? (
										<span className="text-xs text-muted-foreground">
											v{currentPeriod.run.version_number}
										</span>
									) : null}
									<Link
										to={`/pay-runs/${currentPeriod.run.id}`}
										className="text-sm font-medium text-primary underline-offset-4 hover:underline"
										data-testid="current-period-run-link"
									>
										Open pay run
									</Link>
								</div>
							) : (
								<p className="text-sm text-muted-foreground">No run for this period yet.</p>
							)}
						</>
					) : (
						<p className="text-sm text-muted-foreground">No current payroll period.</p>
					)}
				</CardContent>
			</Card>
		</div>
	);
}
