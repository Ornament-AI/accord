import { ClockCounterClockwiseIcon as History } from "@phosphor-icons/react/dist/csr/ClockCounterClockwise";
import {
	type ColumnDef,
	getCoreRowModel,
	type RowData,
	useReactTable,
} from "@tanstack/react-table";
import { useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { DataTableShell } from "@/components/data-table-shell";
import { DataTableSkeleton } from "@/components/data-table-skeleton";
import { EmptyState } from "@/components/empty-state";
import { PageSection, PageShell } from "@/components/page-shell";
import { Badge } from "@/components/ui/badge";
import {
	Breadcrumb,
	BreadcrumbItem,
	BreadcrumbLink,
	BreadcrumbList,
	BreadcrumbPage,
	BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/contexts/AuthContext";
import {
	isCalculateAllowedStatus,
	isDraftStatus,
	type PayrollRunCalculateResult,
	type PayrollRunRosterHistoryResponse,
	type PayrollRunValidateResult,
	parsePayrollRunVersion,
	periodLabel,
	useCalculatePayrollRun,
	usePayrollRun,
	usePayrollRunRosterHistory,
} from "@/lib/api/payroll-runs";
import { getErrorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/utils";

import { PayrollRunRosterTable, type PayrollRunRosterTableHandle } from "./PayrollRunRosterTable";
import { RunStatusBadge } from "./run-status-badge";
import { ValidationFindingsPanel, WorkflowActionBar } from "./workflow";

declare module "@tanstack/react-table" {
	interface ColumnMeta<TData extends RowData, TValue> {
		align?: "left" | "right" | "center";
		className?: string;
	}
}

function PayRunBreadcrumb({ label }: { label: string }) {
	return (
		<Breadcrumb>
			<BreadcrumbList>
				<BreadcrumbItem>
					<BreadcrumbLink render={<Link to="/pay-runs" />}>Pay Runs</BreadcrumbLink>
				</BreadcrumbItem>
				<BreadcrumbSeparator />
				<BreadcrumbItem>
					<BreadcrumbPage>{label}</BreadcrumbPage>
				</BreadcrumbItem>
			</BreadcrumbList>
		</Breadcrumb>
	);
}

function calculateDisabledReason(
	canCreateRun: boolean,
	status: string,
	rosterInitialized: boolean,
	rosterEditing: boolean,
	rosterDirty: boolean,
	rosterSaving: boolean,
): string | null {
	if (!canCreateRun) return "You do not have permission to calculate pay runs.";
	if (status === "draft" && !rosterInitialized) {
		return "Select employees and save the payroll table before calculating.";
	}
	if (rosterSaving) {
		return "Wait for the payroll table to finish saving before calculating.";
	}
	if (rosterEditing || rosterDirty) {
		return "Save or cancel payroll table edits before calculating.";
	}
	if (!isCalculateAllowedStatus(status)) {
		return `Calculate is only available when status is draft, calculated, or rejected (current: ${status}).`;
	}
	return null;
}

const ROSTER_HISTORY_COLUMNS: ColumnDef<PayrollRunRosterHistoryResponse>[] = [
	{
		accessorKey: "action",
		header: "Change",
		cell: ({ row }) => <span className="font-medium">{row.original.action}</span>,
	},
	{
		accessorKey: "changed_fields",
		header: "Fields",
		cell: ({ row }) => row.original.changed_fields.join(", ") || "Employees",
	},
	{
		accessorKey: "changed_employees",
		header: "Employees",
		cell: ({ row }) => (
			<span className="tabular-nums">
				{row.original.changed_employees} changed · {row.original.selected_employees} selected
			</span>
		),
	},
	{
		accessorKey: "actor_name",
		header: "Changed By",
	},
	{
		accessorKey: "created_at",
		header: "When",
		cell: ({ row }) => formatDateTime(row.original.created_at),
	},
];

export default function PayRunDetailPage() {
	const { runId } = useParams<{ runId: string }>();
	const { hasCapability } = useAuth();
	const canCreateRun = hasCapability("create_run");

	const [lastCalculateResult, setLastCalculateResult] = useState<PayrollRunCalculateResult | null>(
		null,
	);
	const [validationResult, setValidationResult] = useState<PayrollRunValidateResult | null>(null);
	const [rosterEditing, setRosterEditing] = useState(false);
	const [rosterDirty, setRosterDirty] = useState(false);
	const [rosterSaving, setRosterSaving] = useState(false);
	const rosterTableRef = useRef<PayrollRunRosterTableHandle>(null);

	const runQuery = usePayrollRun(runId);
	const rosterHistoryQuery = usePayrollRunRosterHistory(runId);
	const calculateMutation = useCalculatePayrollRun(runId ?? "");

	const run = runQuery.data;
	const canEditInputs = Boolean(run && isDraftStatus(run.status));

	const versionInfo = useMemo(() => {
		const fromDetail = parsePayrollRunVersion(run?.current_version);
		return fromDetail ?? lastCalculateResult;
	}, [run?.current_version, lastCalculateResult]);
	const historyTable = useReactTable({
		data: rosterHistoryQuery.data ?? [],
		columns: ROSTER_HISTORY_COLUMNS,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.id,
	});
	const calculateReason = run
		? calculateDisabledReason(
				canCreateRun,
				run.status,
				run.roster_initialized,
				rosterEditing,
				rosterDirty,
				rosterSaving,
			)
		: null;
	const canCalculate = Boolean(run && !calculateReason);

	const handleCalculate = async () => {
		if (!runId || !canCalculate) return;
		try {
			const result = await calculateMutation.mutateAsync();
			setLastCalculateResult(result);
			setValidationResult(null);
			toast.success("Pay run calculated");
		} catch (error) {
			toast.error(getErrorMessage(error, "Failed to calculate pay run."));
		}
	};

	const handleCancelRosterEdit = () => {
		rosterTableRef.current?.cancel();
		setRosterEditing(false);
	};

	const handleSaveRoster = async () => {
		setRosterSaving(true);
		try {
			const saved = await rosterTableRef.current?.save();
			if (saved) setRosterEditing(false);
		} finally {
			setRosterSaving(false);
		}
	};

	if (!runId) {
		return (
			<CapabilityGate capability="create_run" title="Pay Run">
				<AppLayout title="Pay Run">
					<PageShell>
						<EmptyState title="Pay Run Not Found" description="Missing run id." />
					</PageShell>
				</AppLayout>
			</CapabilityGate>
		);
	}

	return (
		<CapabilityGate capability="create_run" title="Pay Run">
			<AppLayout
				title={
					run ? (
						<PayRunBreadcrumb label={periodLabel(run.period_year, run.period_month)} />
					) : (
						"Pay Run"
					)
				}
				actions={
					run ? (
						<WorkflowActionBar
							run={run}
							versionInfo={versionInfo}
							onValidated={setValidationResult}
							onRefresh={() => void runQuery.refetch()}
						>
							<div className="flex items-center gap-2" data-testid="pay-run-menu-actions">
								{canCreateRun ? (
									<Button
										size="xs"
										variant="outline"
										onClick={() => void handleCalculate()}
										disabled={!canCalculate || calculateMutation.isPending}
										title={calculateReason ?? undefined}
										aria-label="Calculate Pay Run"
									>
										{calculateMutation.isPending
											? "Calculating…"
											: run.status === "draft"
												? "Calculate"
												: "Recalculate"}
									</Button>
								) : null}
								{canEditInputs ? (
									rosterEditing ? (
										<>
											<Button
												size="xs"
												variant="outline"
												onClick={handleCancelRosterEdit}
												disabled={rosterSaving}
											>
												Cancel
											</Button>
											<Button
												size="xs"
												onClick={() => void handleSaveRoster()}
												disabled={!rosterDirty || rosterSaving}
											>
												{rosterSaving ? "Saving…" : "Save"}
											</Button>
										</>
									) : (
										<Button size="xs" variant="outline" onClick={() => setRosterEditing(true)}>
											Edit
										</Button>
									)
								) : null}
							</div>
						</WorkflowActionBar>
					) : undefined
				}
			>
				<PageShell data-testid="pay-run-detail-page">
					{runQuery.isLoading ? (
						<div className="grid gap-4">
							<Skeleton className="h-20 w-full" />
							<DataTableSkeleton />
						</div>
					) : null}

					{runQuery.isError ? (
						<ErrorWithRetry
							message={getErrorMessage(runQuery.error, "Failed to load pay run.")}
							onRetry={() => void runQuery.refetch()}
						/>
					) : null}

					{run ? (
						<>
							<PageSection className="grid gap-3">
								<div className="grid gap-3">
									<div className="flex flex-wrap items-center gap-x-3 gap-y-2">
										<h1 className="text-2xl font-semibold tracking-tight">
											{periodLabel(run.period_year, run.period_month)}
										</h1>
										<RunStatusBadge status={run.status} />
										{versionInfo && versionInfo.version_number > 0 ? (
											<Badge variant="secondary">Version {versionInfo.version_number}</Badge>
										) : null}
									</div>
									{validationResult ? <ValidationFindingsPanel result={validationResult} /> : null}
								</div>
								<PayrollRunRosterTable
									ref={rosterTableRef}
									runId={run.id}
									runStatus={run.status}
									editable={canEditInputs}
									editing={rosterEditing}
									periodYear={run.period_year}
									periodMonth={run.period_month}
									onDirtyChange={setRosterDirty}
								/>
							</PageSection>

							<PageSection className="grid gap-3">
								<h2 className="text-base font-semibold">Change History</h2>

								{rosterHistoryQuery.isLoading ? <DataTableSkeleton /> : null}

								{rosterHistoryQuery.isError ? (
									<ErrorWithRetry
										message={getErrorMessage(
											rosterHistoryQuery.error,
											"Failed to load change history.",
										)}
										onRetry={() => void rosterHistoryQuery.refetch()}
									/>
								) : null}

								{!rosterHistoryQuery.isLoading &&
								!rosterHistoryQuery.isError &&
								(rosterHistoryQuery.data?.length ?? 0) === 0 ? (
									<EmptyState icon={History} title="No Changes Yet" />
								) : null}

								{!rosterHistoryQuery.isLoading &&
								!rosterHistoryQuery.isError &&
								(rosterHistoryQuery.data?.length ?? 0) > 0 ? (
									<DataTableShell table={historyTable} tableClassName="min-w-[48rem]" />
								) : null}
							</PageSection>
						</>
					) : null}
				</PageShell>
			</AppLayout>
		</CapabilityGate>
	);
}
