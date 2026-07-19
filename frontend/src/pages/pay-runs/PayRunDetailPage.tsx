import {
	type ColumnDef,
	getCoreRowModel,
	type RowData,
	useReactTable,
} from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import {
	ColumnVisibilityToggle,
	usePersistedColumnVisibility,
} from "@/components/column-visibility";
import { DataTableShell } from "@/components/data-table-shell";
import { DataTableSkeleton } from "@/components/data-table-skeleton";
import { EmptyState } from "@/components/empty-state";
import { PageSection, PageShell } from "@/components/page-shell";
import {
	AlertDialog,
	AlertDialogAction,
	AlertDialogCancel,
	AlertDialogContent,
	AlertDialogDescription,
	AlertDialogFooter,
	AlertDialogHeader,
	AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
	Breadcrumb,
	BreadcrumbItem,
	BreadcrumbLink,
	BreadcrumbList,
	BreadcrumbPage,
	BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/contexts/AuthContext";
import {
	formatCanonicalMoney,
	inputKindLabel,
	isCalculateAllowedStatus,
	isDraftStatus,
	type PayrollEmployeeResult,
	type PayrollRunCalculateResult,
	type PayrollRunInputResponse,
	type PayrollRunTotals,
	type PayrollRunValidateResult,
	parsePayrollRunVersion,
	periodLabel,
	runTypeLabel,
	useCalculatePayrollRun,
	useDeletePayrollRunInput,
	usePayrollRun,
	usePayrollRunInputs,
	usePayrollRunResults,
} from "@/lib/api/payroll-runs";
import { getErrorMessage } from "@/lib/errors";

import { RunStatusBadge } from "./run-status-badge";
import { UpsertInputDialog } from "./UpsertInputDialog";
import { ValidationFindingsPanel, WorkflowActionBar } from "./workflow";

declare module "@tanstack/react-table" {
	interface ColumnMeta<TData extends RowData, TValue> {
		align?: "left" | "right" | "center";
		className?: string;
	}
}

const BREAKDOWN_TOTALS: Array<{ key: keyof PayrollRunTotals; label: string }> = [
	{ key: "earnings_total", label: "Earnings" },
	{ key: "employer_contribution_total", label: "Employer contributions" },
	{ key: "gross_adjustment_total", label: "Gross adjustments" },
	{ key: "ag_deduction_total", label: "AG deductions" },
	{ key: "treasury_deduction_total", label: "Treasury deductions" },
	{ key: "external_recovery_total", label: "External recoveries" },
];

function humanizeCode(value: string): string {
	return value
		.toLowerCase()
		.split("_")
		.filter(Boolean)
		.map((part) =>
			part.length <= 3 ? part.toUpperCase() : part.charAt(0).toUpperCase() + part.slice(1),
		)
		.join(" ");
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

function calculateDisabledReason(canCreateRun: boolean, status: string): string | null {
	if (!canCreateRun) return "You do not have permission to calculate pay runs.";
	if (!isCalculateAllowedStatus(status)) {
		return `Calculate is only available when status is draft, calculated, or rejected (current: ${status}).`;
	}
	return null;
}

type InputColumnsArgs = {
	canEditInputs: boolean;
	employeeNumbers: Map<string, string>;
	onEdit: (input: PayrollRunInputResponse) => void;
	onDelete: (input: PayrollRunInputResponse) => void;
};

function buildInputColumns({
	canEditInputs,
	employeeNumbers,
	onEdit,
	onDelete,
}: InputColumnsArgs): ColumnDef<PayrollRunInputResponse>[] {
	const columns: ColumnDef<PayrollRunInputResponse>[] = [
		{
			accessorKey: "employee_id",
			header: "Employee",
			cell: ({ row }) => (
				<span className="font-medium">
					{employeeNumbers.get(row.original.employee_id) ??
						`Employee ${row.original.employee_id.slice(0, 8)}`}
				</span>
			),
		},
		{
			accessorKey: "component_code",
			header: "Component",
			cell: ({ row }) => humanizeCode(row.original.component_code),
		},
		{
			accessorKey: "input_kind",
			header: "Kind",
			cell: ({ row }) => inputKindLabel(row.original.input_kind),
		},
		{
			accessorKey: "amount",
			header: "Amount",
			cell: ({ row }) => (
				<span className="tabular-nums">{formatCanonicalMoney(row.original.amount)}</span>
			),
			meta: { align: "right" },
		},
		{
			accessorKey: "rate",
			header: "Rate",
			cell: ({ row }) => (
				<span className="tabular-nums">{formatCanonicalMoney(row.original.rate)}</span>
			),
			meta: { align: "right" },
		},
		{
			accessorKey: "reason",
			header: "Reason",
		},
	];

	if (canEditInputs) {
		columns.push({
			id: "actions",
			header: "Actions",
			enableHiding: false,
			meta: { hideFromColumnVisibilityToggle: true },
			cell: ({ row }) => (
				<div className="flex items-center gap-1">
					<Button
						type="button"
						size="xs"
						variant="ghost"
						aria-label={`Edit input ${row.original.component_code}`}
						onClick={(event) => {
							event.stopPropagation();
							onEdit(row.original);
						}}
					>
						Edit
					</Button>
					<Button
						type="button"
						size="xs"
						variant="ghost"
						aria-label={`Delete input ${row.original.component_code}`}
						onClick={(event) => {
							event.stopPropagation();
							onDelete(row.original);
						}}
					>
						Delete
					</Button>
				</div>
			),
		});
	}

	return columns;
}

function FinancialSummary({
	totals,
	employeeCount,
}: {
	totals: PayrollRunTotals;
	employeeCount: number | null;
}) {
	return (
		<div
			className="grid gap-3 lg:grid-cols-[minmax(0,1.35fr)_minmax(20rem,1fr)]"
			data-testid="pay-run-totals"
		>
			<div className="grid gap-3 sm:grid-cols-3">
				<Card size="sm" className="sm:col-span-3">
					<CardHeader>
						<CardTitle className="text-sm font-medium text-muted-foreground">Net Payable</CardTitle>
					</CardHeader>
					<CardContent>
						<p className="text-3xl font-semibold tracking-tight tabular-nums">
							{formatCanonicalMoney(totals.net_payable)}
						</p>
					</CardContent>
				</Card>
				<Card size="sm">
					<CardHeader>
						<CardTitle className="text-sm text-muted-foreground">Gross Pay</CardTitle>
					</CardHeader>
					<CardContent>
						<p className="text-lg font-semibold tabular-nums">
							{formatCanonicalMoney(totals.gross_total)}
						</p>
					</CardContent>
				</Card>
				<Card size="sm">
					<CardHeader>
						<CardTitle className="text-sm text-muted-foreground">Total Deductions</CardTitle>
					</CardHeader>
					<CardContent>
						<p className="text-lg font-semibold tabular-nums">
							{formatCanonicalMoney(totals.deductions_total)}
						</p>
					</CardContent>
				</Card>
				<Card size="sm">
					<CardHeader>
						<CardTitle className="text-sm text-muted-foreground">Employees</CardTitle>
					</CardHeader>
					<CardContent>
						<p className="text-lg font-semibold tabular-nums">
							{employeeCount == null ? "—" : employeeCount.toLocaleString("en-IN")}
						</p>
					</CardContent>
				</Card>
			</div>

			<Card size="sm">
				<CardHeader className="border-b">
					<CardTitle>Payroll breakdown</CardTitle>
				</CardHeader>
				<CardContent>
					<dl className="grid gap-3">
						{BREAKDOWN_TOTALS.map((item) => (
							<div key={item.key} className="flex items-center justify-between gap-4">
								<dt className="text-muted-foreground">{item.label}</dt>
								<dd className="font-medium tabular-nums">
									{formatCanonicalMoney(totals[item.key])}
								</dd>
							</div>
						))}
					</dl>
				</CardContent>
			</Card>
		</div>
	);
}

function buildEmployeeResultColumns(): ColumnDef<PayrollEmployeeResult>[] {
	return [
		{
			accessorKey: "employee_number",
			header: "Employee",
			cell: ({ row }) => <span className="font-medium">{row.original.employee_number}</span>,
		},
		{
			accessorKey: "earnings_total",
			header: "Earnings",
			cell: ({ row }) => (
				<span className="tabular-nums">{formatCanonicalMoney(row.original.earnings_total)}</span>
			),
			meta: { align: "right" },
		},
		{
			accessorKey: "deductions_total",
			header: "Deductions",
			cell: ({ row }) => (
				<span className="tabular-nums">{formatCanonicalMoney(row.original.deductions_total)}</span>
			),
			meta: { align: "right" },
		},
		{
			accessorKey: "net_payable",
			header: "Net payable",
			cell: ({ row }) => (
				<span className="font-semibold tabular-nums">
					{formatCanonicalMoney(row.original.net_payable)}
				</span>
			),
			meta: { align: "right" },
		},
	];
}

export default function PayRunDetailPage() {
	const { runId } = useParams<{ runId: string }>();
	const { hasCapability } = useAuth();
	const canCreateRun = hasCapability("create_run");

	const [inputDialogOpen, setInputDialogOpen] = useState(false);
	const [editingInput, setEditingInput] = useState<PayrollRunInputResponse | null>(null);
	const [deletingInput, setDeletingInput] = useState<PayrollRunInputResponse | null>(null);
	const [lastCalculateResult, setLastCalculateResult] = useState<PayrollRunCalculateResult | null>(
		null,
	);
	const [validationResult, setValidationResult] = useState<PayrollRunValidateResult | null>(null);
	const [columnVisibility, setColumnVisibility] = usePersistedColumnVisibility(
		"accord:pay-run-inputs:columns",
		{},
	);

	const runQuery = usePayrollRun(runId);
	const inputsQuery = usePayrollRunInputs(runId);
	const calculateMutation = useCalculatePayrollRun(runId ?? "");
	const deleteMutation = useDeletePayrollRunInput(runId ?? "");

	const run = runQuery.data;
	const inputs = inputsQuery.data ?? [];
	const canEditInputs = Boolean(run && isDraftStatus(run.status));

	const versionInfo = useMemo(() => {
		const fromDetail = parsePayrollRunVersion(run?.current_version);
		return fromDetail ?? lastCalculateResult;
	}, [run?.current_version, lastCalculateResult]);
	const resultsQuery = usePayrollRunResults(runId, Boolean(versionInfo));
	// Ignore cached results that belong to a prior calculation version.
	const resultsAreCurrent = Boolean(
		resultsQuery.data &&
			versionInfo &&
			resultsQuery.data.version.version_number === versionInfo.version_number &&
			(!versionInfo.version_id || resultsQuery.data.version.id === versionInfo.version_id),
	);
	const employeeResults = resultsAreCurrent ? (resultsQuery.data?.employees ?? []) : [];
	const totals = resultsAreCurrent
		? (resultsQuery.data?.totals ?? versionInfo?.totals)
		: versionInfo?.totals;
	const resultsPending =
		Boolean(versionInfo) &&
		!resultsAreCurrent &&
		(resultsQuery.isLoading || resultsQuery.isFetching);
	const employeeNumbers = useMemo(
		() => new Map(employeeResults.map((result) => [result.employee_id, result.employee_number])),
		[employeeResults],
	);

	const inputColumns = useMemo(
		() =>
			buildInputColumns({
				canEditInputs,
				employeeNumbers,
				onEdit: (input) => {
					setEditingInput(input);
					setInputDialogOpen(true);
				},
				onDelete: (input) => setDeletingInput(input),
			}),
		[canEditInputs, employeeNumbers],
	);

	const table = useReactTable({
		data: inputs,
		columns: inputColumns,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.id,
		state: { columnVisibility },
		onColumnVisibilityChange: setColumnVisibility,
	});
	const employeeResultsTable = useReactTable({
		data: employeeResults,
		columns: buildEmployeeResultColumns(),
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.employee_id,
	});

	const calculateReason = run ? calculateDisabledReason(canCreateRun, run.status) : null;
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

	const handleConfirmDelete = async () => {
		if (!deletingInput) return;
		try {
			await deleteMutation.mutateAsync(deletingInput.id);
			setDeletingInput(null);
			toast.success("Input deleted");
		} catch (error) {
			toast.error(getErrorMessage(error, "Failed to delete input."));
		}
	};

	if (!runId) {
		return (
			<CapabilityGate capability="create_run" title="Pay run">
				<AppLayout title="Pay run">
					<PageShell>
						<EmptyState title="Pay run not found" description="Missing run id." />
					</PageShell>
				</AppLayout>
			</CapabilityGate>
		);
	}

	return (
		<CapabilityGate capability="create_run" title="Pay run">
			<AppLayout
				title={
					run ? (
						<PayRunBreadcrumb
							label={`${periodLabel(run.period_year, run.period_month)} · ${runTypeLabel(run.run_type)}`}
						/>
					) : (
						"Pay run"
					)
				}
				actions={
					run && canCreateRun ? (
						<Button
							size="xs"
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
								<div className="flex flex-wrap items-center gap-x-3 gap-y-2">
									<h1 className="text-2xl font-semibold tracking-tight">
										{periodLabel(run.period_year, run.period_month)}
									</h1>
									<span className="text-muted-foreground">{runTypeLabel(run.run_type)}</span>
									<RunStatusBadge status={run.status} />
									{versionInfo && versionInfo.version_number > 0 ? (
										<span className="text-xs text-muted-foreground">
											Version {versionInfo.version_number}
										</span>
									) : null}
								</div>
								<WorkflowActionBar
									run={run}
									versionInfo={versionInfo}
									onValidated={setValidationResult}
									onRefresh={() => void runQuery.refetch()}
								/>
								{validationResult ? <ValidationFindingsPanel result={validationResult} /> : null}
							</PageSection>

							<PageSection className="grid gap-3">
								<div>
									<h2 className="text-base font-semibold">Payroll results</h2>
									<p className="text-sm text-muted-foreground">
										The payable outcome and employee-level calculation for this run.
									</p>
								</div>
								{versionInfo && totals ? (
									<>
										<FinancialSummary
											totals={totals}
											employeeCount={
												resultsPending || resultsQuery.isError ? null : employeeResults.length
											}
										/>
										{resultsPending ? <DataTableSkeleton /> : null}
										{!resultsPending && resultsQuery.isError ? (
											<ErrorWithRetry
												message={getErrorMessage(
													resultsQuery.error,
													"Failed to load employee results.",
												)}
												onRetry={() => void resultsQuery.refetch()}
											/>
										) : null}
										{!resultsPending && !resultsQuery.isError && employeeResults.length > 0 ? (
											<div className="grid gap-2">
												<h3 className="text-sm font-medium">Employee results</h3>
												<DataTableShell
													table={employeeResultsTable}
													tableClassName="min-w-[42rem]"
												/>
											</div>
										) : null}
										{!resultsQuery.isLoading &&
										!resultsQuery.isError &&
										employeeResults.length === 0 ? (
											<p className="text-sm text-muted-foreground">
												No employee results were produced for this run.
											</p>
										) : null}
									</>
								) : (
									<EmptyState
										title="No calculated results"
										description="Calculate this run to produce payroll totals and employee results."
									/>
								)}
							</PageSection>

							<PageSection className="grid gap-3">
								<div className="flex flex-wrap items-center justify-between gap-2">
									<div>
										<h2 className="text-base font-semibold">Run adjustments</h2>
										<p className="text-sm text-muted-foreground">
											One-time amounts, overrides, and exceptions applied to this run.
										</p>
									</div>
									<div className="flex items-center gap-2">
										<ColumnVisibilityToggle
											table={table}
											iconOnly
											triggerClassName="justify-center"
										/>
										{canEditInputs ? (
											<Button
												size="xs"
												onClick={() => {
													setEditingInput(null);
													setInputDialogOpen(true);
												}}
											>
												Add
											</Button>
										) : null}
									</div>
								</div>

								{inputsQuery.isLoading ? <DataTableSkeleton /> : null}

								{inputsQuery.isError ? (
									<ErrorWithRetry
										message={getErrorMessage(inputsQuery.error, "Failed to load inputs.")}
										onRetry={() => void inputsQuery.refetch()}
									/>
								) : null}

								{!inputsQuery.isLoading && !inputsQuery.isError && inputs.length === 0 ? (
									<p className="text-sm text-muted-foreground">
										{canEditInputs
											? "No inputs yet. Add an exception, override, or one-time amount."
											: "No inputs on this run."}
									</p>
								) : null}

								{!inputsQuery.isLoading && !inputsQuery.isError && inputs.length > 0 ? (
									<DataTableShell table={table} tableClassName="min-w-[54rem]" />
								) : null}
							</PageSection>
						</>
					) : null}
				</PageShell>

				{canEditInputs ? (
					<UpsertInputDialog
						open={inputDialogOpen}
						onOpenChange={(open) => {
							setInputDialogOpen(open);
							if (!open) setEditingInput(null);
						}}
						runId={runId}
						editing={editingInput}
					/>
				) : null}

				<AlertDialog
					open={Boolean(deletingInput)}
					onOpenChange={(open) => {
						if (!open) setDeletingInput(null);
					}}
				>
					<AlertDialogContent>
						<AlertDialogHeader>
							<AlertDialogTitle>Delete input?</AlertDialogTitle>
							<AlertDialogDescription>
								This removes the {deletingInput?.component_code} input for employee{" "}
								{deletingInput?.employee_id}. This cannot be undone.
							</AlertDialogDescription>
						</AlertDialogHeader>
						<AlertDialogFooter>
							<AlertDialogCancel>Cancel</AlertDialogCancel>
							<AlertDialogAction
								variant="destructive"
								onClick={() => void handleConfirmDelete()}
								disabled={deleteMutation.isPending}
							>
								{deleteMutation.isPending ? "Deleting…" : "Delete"}
							</AlertDialogAction>
						</AlertDialogFooter>
					</AlertDialogContent>
				</AlertDialog>
			</AppLayout>
		</CapabilityGate>
	);
}
