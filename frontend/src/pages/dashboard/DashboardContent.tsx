import { Banknote, Users } from "lucide-react";
import { Link } from "react-router";

import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Skeleton } from "@/components/ui/skeleton";
import { useDashboard } from "@/lib/api/dashboard";
import { getErrorMessage } from "@/lib/errors";

import { PipelineStrip } from "./PipelineStrip";
import { PostedComparisonChart } from "./PostedComparisonChart";
import { RecentArtifactsList } from "./RecentArtifactsList";
import { StatCards } from "./StatCards";

function DashboardSkeleton() {
	return (
		<div className="flex flex-col gap-6" data-testid="dashboard-loading">
			<div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
				<Skeleton className="h-28 w-full" />
				<Skeleton className="h-28 w-full" />
				<Skeleton className="h-28 w-full" />
				<Skeleton className="h-28 w-full" />
			</div>
			<Skeleton className="h-36 w-full" />
			<Skeleton className="h-64 w-full" />
		</div>
	);
}

export function DashboardContent() {
	const dashboardQuery = useDashboard();

	if (dashboardQuery.isLoading) {
		return <DashboardSkeleton />;
	}

	if (dashboardQuery.isError || !dashboardQuery.data) {
		return (
			<div data-testid="dashboard-error">
				<ErrorWithRetry
					message={getErrorMessage(dashboardQuery.error, "Failed to load dashboard.")}
					onRetry={() => {
						void dashboardQuery.refetch();
					}}
				/>
			</div>
		);
	}

	const data = dashboardQuery.data;
	const hasEmployees = data.headcount.active_employees > 0;
	const hasPostedRuns = data.latest_posted != null;

	return (
		<div className="flex flex-col gap-6" data-testid="dashboard-content">
			{!hasEmployees ? (
				<Card data-testid="empty-employees">
					<CardContent className="pt-6">
						<EmptyState
							icon={Users}
							title="No employees yet"
							description="Add employees to start building payroll headcount and pay runs."
						>
							<Button render={<Link to="/employees" />}>Go to Employees</Button>
						</EmptyState>
					</CardContent>
				</Card>
			) : null}

			<StatCards data={data} />
			<PipelineStrip data={data} />

			{hasPostedRuns && data.latest_posted ? (
				<PostedComparisonChart latest={data.latest_posted} previous={data.previous_posted} />
			) : (
				<Card data-testid="empty-posted-runs">
					<CardContent className="pt-6">
						<EmptyState
							icon={Banknote}
							title="No posted runs yet"
							description="Post a pay run to see totals, variance, and comparison charts here."
						>
							<Button render={<Link to="/pay-runs" />}>Go to Pay Runs</Button>
						</EmptyState>
					</CardContent>
				</Card>
			)}

			<RecentArtifactsList artifacts={data.recent_artifacts} />
		</div>
	);
}
