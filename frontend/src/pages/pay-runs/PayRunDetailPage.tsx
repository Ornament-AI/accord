import {
	type ColumnDef,
	getCoreRowModel,
	type RowData,
	useReactTable,
} from "@tanstack/react-table";
import { ArrowLeft, Calculator, Pencil, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { DataTableShell } from "@/components/data-table-shell";
import { DataTableSkeleton } from "@/components/data-table-skeleton";
import { EmptyState } from "@/components/empty-state";
import { PageSection, PageShell } from "@/components/page-shell";
import { PageToolbar } from "@/components/page-toolbar";
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
import { Badge } from "@/components/ui/badge";
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

const TOTAL_LABELS: Array<{ key: keyof PayrollRunTotals; label: string }> = [
	{ key: "earnings_total", label: "Earnings" },
	{ key: "employer_contribution_total", label: "Employer contribution" },
	{ key: "gross_adjustment_total", label: "Gross adjustment" },
	{ key: "gross_total", label: "Gross" },
	{ key: "ag_deduction_total", label: "AG deduction" },
	{ key: "treasury_deduction_total", label: "Treasury deduction" },
	{ key: "external_recovery_total", label: "External recovery" },
	{ key: "deductions_total", label: "Deductions" },
	{ key: "net_payable", label: "Net payable" },
];

function calculateDisabledReason(canCreateRun: boolean, status: string): string | null {
	if (!canCreateRun) return "You do not have permission to calculate pay runs.";
	if (!isCalculateAllowedStatus(status)) {
		return `Calculate is only available when status is draft, calculated, or rejected (current: ${status}).`;
	}
	return null;
}

type InputColumnsArgs = {
	canEditInputs: boolean;
	onEdit: (input: PayrollRunInputResponse) => void;
	onDelete: (input: PayrollRunInputResponse) => void;
};

function buildInputColumns({
	canEditInputs,
	onEdit,
	onDelete,
}: InputColumnsArgs): ColumnDef<PayrollRunInputResponse>[] {
	const columns: ColumnDef<PayrollRunInputResponse>[] = [
		{
			accessorKey: "employee_id",
			header: "Employee",
		},
		{
			accessorKey: "component_code",
			header: "Component",
		},
		{
			accessorKey: "input_kind",
			header: "Kind",
			cell: ({ row }) => inputKindLabel(row.original.input_kind),
		},
		{
			accessorKey: "amount",
			header: "Amount",
			cell: ({ row }) => formatCanonicalMoney(row.original.amount),
			meta: { align: "right" },
		},
		{
			accessorKey: "rate",
			header: "Rate",
			cell: ({ row }) => formatCanonicalMoney(row.original.rate),
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
			cell: ({ row }) => (
				<div className="flex items-center gap-1">
					<Button
						type="button"
						size="sm"
						variant="ghost"
						aria-label={`Edit input ${row.original.component_code}`}
						onClick={(event) => {
							event.stopPropagation();
							onEdit(row.original);
						}}
					>
						<Pencil className="size-4" />
						Edit
					</Button>
					<Button
						type="button"
						size="sm"
						variant="ghost"
						aria-label={`Delete input ${row.original.component_code}`}
						onClick={(event) => {
							event.stopPropagation();
							onDelete(row.original);
						}}
					>
						<Trash2 className="size-4" />
						Delete
					</Button>
				</div>
			),
		});
	}

	return columns;
}

function TotalsCards({ totals }: { totals: PayrollRunTotals }) {
	const entries = TOTAL_LABELS.filter(
		(item) => totals[item.key] != null && totals[item.key] !== "",
	);
	const extraKeys = Object.keys(totals).filter(
		(key) => !TOTAL_LABELS.some((item) => item.key === key) && totals[key],
	);

	if (entries.length === 0 && extraKeys.length === 0) {
		return <p className="text-sm text-muted-foreground">No totals available yet.</p>;
	}

	return (
		<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="pay-run-totals">
			{entries.map((item) => (
				<Card key={item.key} size="sm">
					<CardHeader className="border-b">
						<CardTitle className="text-sm font-medium text-muted-foreground">
							{item.label}
						</CardTitle>
					</CardHeader>
					<CardContent>
						<p className="text-lg font-semibold tracking-tight">
							{formatCanonicalMoney(totals[item.key])}
						</p>
					</CardContent>
				</Card>
			))}
			{extraKeys.map((key) => (
				<Card key={key} size="sm">
					<CardHeader className="border-b">
						<CardTitle className="text-sm font-medium text-muted-foreground">{key}</CardTitle>
					</CardHeader>
					<CardContent>
						<p className="text-lg font-semibold tracking-tight">
							{formatCanonicalMoney(totals[key])}
						</p>
					</CardContent>
				</Card>
			))}
		</div>
	);
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

	const inputColumns = useMemo(
		() =>
			buildInputColumns({
				canEditInputs,
				onEdit: (input) => {
					setEditingInput(input);
					setInputDialogOpen(true);
				},
				onDelete: (input) => setDeletingInput(input),
			}),
		[canEditInputs],
	);

	const table = useReactTable({
		data: inputs,
		columns: inputColumns,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.id,
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
					run
						? `${periodLabel(run.period_year, run.period_month)} · ${runTypeLabel(run.run_type)}`
						: "Pay run"
				}
				actions={
					run && canCreateRun ? (
						<Button
							size="sm"
							onClick={() => void handleCalculate()}
							disabled={!canCalculate || calculateMutation.isPending}
							title={calculateReason ?? undefined}
							aria-label="Calculate pay run"
						>
							<Calculator className="size-4" />
							{calculateMutation.isPending ? "Calculating…" : "Calculate"}
						</Button>
					) : undefined
				}
			>
				<PageShell data-testid="pay-run-detail-page">
					<PageToolbar>
						<Button
							variant="ghost"
							size="sm"
							render={<Link to="/pay-runs" />}
							aria-label="Back to pay runs"
						>
							<ArrowLeft className="size-4" />
							Pay runs
						</Button>
					</PageToolbar>

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
							<PageSection>
								<div className="flex flex-wrap items-center gap-3">
									<h2 className="text-xl font-semibold tracking-tight">
										{periodLabel(run.period_year, run.period_month)}
									</h2>
									<span className="text-muted-foreground">{runTypeLabel(run.run_type)}</span>
									<RunStatusBadge status={run.status} />
									{versionInfo?.engine_version ? (
										<Badge variant="outline">Engine {versionInfo.engine_version}</Badge>
									) : null}
									{versionInfo && versionInfo.version_number > 0 ? (
										<Badge variant="outline">v{versionInfo.version_number}</Badge>
									) : null}
									{versionInfo?.content_hash ? (
										<Badge variant="muted" title={versionInfo.content_hash}>
											Hash {versionInfo.content_hash.slice(0, 12)}
										</Badge>
									) : null}
								</div>
							</PageSection>

							<PageSection className="grid gap-3">
								<WorkflowActionBar
									run={run}
									versionInfo={versionInfo}
									onValidated={setValidationResult}
									onRefresh={() => void runQuery.refetch()}
								/>
								{validationResult ? <ValidationFindingsPanel result={validationResult} /> : null}
							</PageSection>

							<PageSection className="grid gap-3">
								<div className="flex flex-wrap items-center justify-between gap-2">
									<h3 className="text-sm font-medium">Inputs</h3>
									{canEditInputs ? (
										<Button
											size="sm"
											onClick={() => {
												setEditingInput(null);
												setInputDialogOpen(true);
											}}
										>
											<Plus className="size-4" />
											Add input
										</Button>
									) : null}
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
									<DataTableShell table={table} />
								) : null}
							</PageSection>

							<PageSection className="grid gap-3">
								<h3 className="text-sm font-medium">Results</h3>
								{/*
								  CONTRACT GAP: OpenAPI has no per-employee results-read endpoint and no
								  run-versions list endpoint. Show totals (+ version metadata in the header)
								  only. A per-employee results table can be added here when an endpoint exists.
								*/}
								{versionInfo ? (
									<TotalsCards totals={versionInfo.totals} />
								) : (
									<p className="text-sm text-muted-foreground">
										No calculated results yet. Run Calculate to produce totals.
									</p>
								)}
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
