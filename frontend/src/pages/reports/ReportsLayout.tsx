import { ChartBarIcon as WalletCards } from "@phosphor-icons/react/dist/csr/ChartBar";
import { CircleNotchIcon as Loader2 } from "@phosphor-icons/react/dist/csr/CircleNotch";
import { DownloadSimpleIcon as Download } from "@phosphor-icons/react/dist/csr/DownloadSimple";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Outlet, useSearchParams } from "react-router";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { EmptyState } from "@/components/empty-state";
import { PageSection, PageShell } from "@/components/page-shell";
import { PageSkeleton } from "@/components/page-skeleton";
import { PageToolbar } from "@/components/page-toolbar";
import { Button } from "@/components/ui/button";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { type PayrollRunListItem, usePayrollRuns } from "@/lib/api/payroll-runs";
import {
	isActiveJobStatus,
	jobArtifactId,
	jobErrorMessage,
	reportQueryKeys,
	useArtifactsList,
	useDownloadArtifact,
	useExportReports,
	useReportJob,
} from "@/lib/api/reports";
import { getErrorMessage } from "@/lib/errors";
import { periodLabel } from "@/lib/payroll-display";

import { ArtifactsSection } from "./ArtifactsSection";

const ARTIFACTS_PAGE_SIZE = 20;

function postedRunLabel(run: PayrollRunListItem): string {
	return periodLabel(run.period_year, run.period_month);
}

export type ReportsOutletContext = {
	selectedRunId: string | null;
	postedRuns: PayrollRunListItem[];
};

export default function ReportsLayout() {
	const queryClient = useQueryClient();
	const [searchParams, setSearchParams] = useSearchParams();
	const runIdFromUrl = searchParams.get("runId");
	const [selectedRunId, setSelectedRunId] = useState<string | null>(runIdFromUrl);
	const [artifactPage, setArtifactPage] = useState(1);
	const [exportJobId, setExportJobId] = useState<string | undefined>();
	const downloadedArtifactRef = useRef<string | null>(null);

	const runsQuery = usePayrollRuns({ status: "posted" });
	const exportMutation = useExportReports();
	const exportJobQuery = useReportJob(exportJobId);
	const downloadMutation = useDownloadArtifact();

	const postedRuns = runsQuery.data ?? [];

	useEffect(() => {
		if (runIdFromUrl && runIdFromUrl !== selectedRunId) {
			setSelectedRunId(runIdFromUrl);
		}
	}, [runIdFromUrl, selectedRunId]);

	useEffect(() => {
		if (!runsQuery.isSuccess || !selectedRunId) return;
		if (!postedRuns.some((run) => run.id === selectedRunId)) {
			setSelectedRunId(null);
			setArtifactPage(1);
			setExportJobId(undefined);
			if (runIdFromUrl) {
				const next = new URLSearchParams(searchParams);
				next.delete("runId");
				setSearchParams(next, { replace: true });
			}
		}
	}, [postedRuns, runIdFromUrl, runsQuery.isSuccess, searchParams, selectedRunId, setSearchParams]);

	useEffect(() => {
		const artifactId = jobArtifactId(exportJobQuery.data);
		if (
			exportJobQuery.data?.status === "succeeded" &&
			artifactId &&
			downloadedArtifactRef.current !== artifactId
		) {
			downloadedArtifactRef.current = artifactId;
			void queryClient.invalidateQueries({ queryKey: reportQueryKeys.artifacts() });
			downloadMutation.mutate(
				{
					artifactId,
					preferFilename: exportJobQuery.data.result?.filename,
				},
				{
					onSettled: () => {
						setExportJobId(undefined);
					},
				},
			);
		}
	}, [exportJobQuery.data, downloadMutation, queryClient]);

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
	const exportBusy =
		exportMutation.isPending ||
		downloadMutation.isPending ||
		isActiveJobStatus(exportJobQuery.data?.status);
	const exportError =
		jobErrorMessage(exportJobQuery.data) ??
		(exportMutation.error ? getErrorMessage(exportMutation.error, "Export failed.") : null);

	function updateSelectedRun(runId: string | null) {
		setSelectedRunId(runId);
		setArtifactPage(1);
		setExportJobId(undefined);
		const next = new URLSearchParams(searchParams);
		if (runId) {
			next.set("runId", runId);
		} else {
			next.delete("runId");
		}
		setSearchParams(next, { replace: true });
	}

	function handleExport() {
		if (!selectedRunId) return;
		downloadedArtifactRef.current = null;
		exportMutation.mutate(
			{ posted_run_id: selectedRunId },
			{
				onSuccess: (result) => {
					setExportJobId(result.job_id);
				},
			},
		);
	}

	const outletContext: ReportsOutletContext = {
		selectedRunId,
		postedRuns,
	};

	return (
		<CapabilityGate capability="generate_reports" title="Reports">
			<AppLayout title="Reports">
				<PageShell data-testid="reports-page">
					{runsLoading ? <PageSkeleton /> : null}

					{runsError ? (
						<ErrorWithRetry
							message={getErrorMessage(runsQuery.error, "Failed to load posted pay runs.")}
							onRetry={() => void runsQuery.refetch()}
						/>
					) : null}

					{noPostedRuns ? (
						<EmptyState
							icon={WalletCards}
							title="No Posted Runs Yet"
							description="Post a payroll run before generating reports."
						/>
					) : null}

					{!runsLoading && !runsError && !noPostedRuns ? (
						<>
							<PageSection className="flex flex-col gap-3">
								<PageToolbar
									trailing={
										<Button
											type="button"
											onClick={() => void handleExport()}
											disabled={!selectedRunId || exportBusy}
											aria-label="Export all report sheets as Excel ZIP"
										>
											{exportBusy ? (
												<Loader2 className="size-4 animate-spin" aria-hidden="true" />
											) : (
												<Download className="size-4" aria-hidden="true" />
											)}
											Export
										</Button>
									}
								>
									<div className="flex min-w-[16rem] flex-col gap-2">
										<Label htmlFor="reports-posted-run">Posted Run</Label>
										<Select
											value={selectedRunId}
											onValueChange={(value) => {
												updateSelectedRun(value || null);
											}}
										>
											<SelectTrigger
												id="reports-posted-run"
												className="w-full max-w-md"
												aria-label="Select Posted Run"
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
										Select a posted run to preview and export reports.
									</p>
								) : null}
								{exportError ? (
									<p className="text-destructive text-sm" role="alert">
										{exportError}
									</p>
								) : null}
							</PageSection>

							<PageSection className="flex flex-col gap-3">
								<Outlet context={outletContext} />
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
