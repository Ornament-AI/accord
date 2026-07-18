import { WalletCards } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { DataTableSkeleton } from "@/components/data-table-skeleton";
import { EmptyState } from "@/components/empty-state";
import { PageSection, PageShell } from "@/components/page-shell";
import { PageToolbar } from "@/components/page-toolbar";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import {
	type PayrollRunListItem,
	periodLabel,
	runTypeLabel,
	usePayrollRuns,
} from "@/lib/api/payroll-runs";
import { useArtifactsList, useReportCatalog } from "@/lib/api/reports";
import { getErrorMessage } from "@/lib/errors";

import { ArtifactsSection } from "./ArtifactsSection";
import { ReportCatalogSection } from "./ReportCatalogSection";
import { useReportGeneration } from "./use-report-generation";

const ARTIFACTS_PAGE_SIZE = 20;

function postedRunLabel(run: PayrollRunListItem): string {
	return `${periodLabel(run.period_year, run.period_month)} · ${runTypeLabel(run.run_type)}`;
}

export default function ReportsPage() {
	const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
	const [artifactPage, setArtifactPage] = useState(1);

	const runsQuery = usePayrollRuns({ status: "posted" });
	const catalogQuery = useReportCatalog();
	const generation = useReportGeneration();

	const postedRuns = runsQuery.data ?? [];

	useEffect(() => {
		if (selectedRunId && !postedRuns.some((run) => run.id === selectedRunId)) {
			setSelectedRunId(null);
		}
	}, [postedRuns, selectedRunId]);

	const artifactParams = useMemo(
		() => ({
			posted_run_id: selectedRunId,
			page: artifactPage,
			page_size: ARTIFACTS_PAGE_SIZE,
		}),
		[selectedRunId, artifactPage],
	);
	const artifactsQuery = useArtifactsList(artifactParams);

	const runsLoading = runsQuery.isLoading;
	const runsError = runsQuery.isError;
	const noPostedRuns = !runsLoading && !runsError && postedRuns.length === 0;

	return (
		<CapabilityGate capability="generate_reports" title="Reports">
			<AppLayout title="Reports">
				<PageShell data-testid="reports-page">
					{runsLoading ? <DataTableSkeleton rows={3} /> : null}

					{runsError ? (
						<ErrorWithRetry
							message={getErrorMessage(runsQuery.error, "Failed to load posted pay runs.")}
							onRetry={() => void runsQuery.refetch()}
						/>
					) : null}

					{noPostedRuns ? (
						<EmptyState
							icon={WalletCards}
							title="No posted runs yet"
							description="Post a payroll run before generating reports."
						/>
					) : null}

					{!runsLoading && !runsError && !noPostedRuns ? (
						<>
							<PageSection className="flex flex-col gap-3">
								<PageToolbar>
									<div className="flex min-w-[16rem] flex-col gap-2">
										<Label htmlFor="reports-posted-run">Posted run</Label>
										<Select
											value={selectedRunId}
											onValueChange={(value) => {
												setSelectedRunId(value || null);
												setArtifactPage(1);
											}}
										>
											<SelectTrigger
												id="reports-posted-run"
												className="w-full max-w-md"
												aria-label="Select posted run"
											>
												<SelectValue placeholder="Select a posted run">
													{(value: string | null) => {
														const run = postedRuns.find((item) => item.id === value);
														return run ? postedRunLabel(run) : "Select a posted run";
													}}
												</SelectValue>
											</SelectTrigger>
											<SelectContent>
												{postedRuns.map((run) => (
													<SelectItem key={run.id} value={run.id}>
														{postedRunLabel(run)}
													</SelectItem>
												))}
											</SelectContent>
										</Select>
									</div>
								</PageToolbar>
								{!selectedRunId ? (
									<p className="text-muted-foreground text-sm">
										Select a posted run to generate reports.
									</p>
								) : null}
							</PageSection>

							<PageSection className="flex flex-col gap-3">
								<div>
									<h2 className="text-base font-semibold tracking-tight">Report types</h2>
									<p className="text-muted-foreground text-sm">
										Generate Excel or PDF exports for the selected posted run.
									</p>
								</div>
								<ReportCatalogSection
									entries={catalogQuery.data?.report_types}
									isLoading={catalogQuery.isLoading}
									isError={catalogQuery.isError}
									error={catalogQuery.error}
									onRetry={() => void catalogQuery.refetch()}
									postedRunId={selectedRunId}
									generationDisabled={!selectedRunId}
									generation={generation}
								/>
							</PageSection>

							<ArtifactsSection
								items={artifactsQuery.data?.items}
								isLoading={artifactsQuery.isLoading}
								isError={artifactsQuery.isError}
								error={artifactsQuery.error}
								onRetry={() => void artifactsQuery.refetch()}
								runs={postedRuns}
								selectedRunId={selectedRunId}
								page={artifactsQuery.data?.page ?? artifactPage}
								totalPages={artifactsQuery.data?.total_pages ?? 1}
								onPageChange={setArtifactPage}
							/>
						</>
					) : null}
				</PageShell>
			</AppLayout>
		</CapabilityGate>
	);
}
