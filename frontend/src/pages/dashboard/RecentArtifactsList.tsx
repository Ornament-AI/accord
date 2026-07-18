import { FileText } from "lucide-react";
import { Link } from "react-router";

import { EmptyState } from "@/components/empty-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { DashboardRecentArtifact } from "@/lib/api/dashboard";
import { formatDateTime } from "@/lib/utils";

const MAX_ARTIFACTS = 5;

type RecentArtifactsListProps = {
	artifacts: DashboardRecentArtifact[];
};

export function RecentArtifactsList({ artifacts }: RecentArtifactsListProps) {
	const items = artifacts.slice(0, MAX_ARTIFACTS);

	return (
		<Card data-testid="dashboard-recent-artifacts">
			<CardHeader className="border-b">
				<CardTitle className="text-sm font-medium">Recent artifacts</CardTitle>
			</CardHeader>
			<CardContent>
				{items.length === 0 ? (
					<EmptyState
						icon={FileText}
						title="No artifacts yet"
						description="Generated payroll reports will appear here."
					/>
				) : (
					<ul className="divide-y">
						{items.map((artifact) => (
							<li key={artifact.id}>
								<Link
									to="/reports"
									className="flex items-start justify-between gap-3 py-3 text-sm transition-colors hover:text-primary"
									data-testid={`artifact-link-${artifact.id}`}
								>
									<span className="min-w-0">
										<span className="block truncate font-mono text-xs">{artifact.report_type}</span>
										<span className="text-xs text-muted-foreground">
											{formatDateTime(artifact.created_at)}
										</span>
									</span>
									<span className="shrink-0 text-xs text-muted-foreground">Reports</span>
								</Link>
							</li>
						))}
					</ul>
				)}
			</CardContent>
		</Card>
	);
}
