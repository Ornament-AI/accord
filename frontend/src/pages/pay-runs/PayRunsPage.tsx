import { MoneyIcon as WalletCards } from "@phosphor-icons/react/dist/csr/Money";
import {
	type ColumnDef,
	getCoreRowModel,
	type RowData,
	useReactTable,
} from "@tanstack/react-table";
import { useState } from "react";
import { useNavigate } from "react-router";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { DataTableShell } from "@/components/data-table-shell";
import { DataTableSkeleton } from "@/components/data-table-skeleton";
import { EmptyState } from "@/components/empty-state";
import { PageSection, PageShell } from "@/components/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { useAuth } from "@/contexts/AuthContext";
import {
	type PayrollPeriodResponse,
	type PayrollRunListItem,
	periodLabel,
	runTypeLabel,
	usePayrollPeriods,
	usePayrollRuns,
} from "@/lib/api/payroll-runs";
import { getErrorMessage } from "@/lib/errors";

import { CreatePeriodDialog } from "./CreatePeriodDialog";
import { CreateRunDialog } from "./CreateRunDialog";
import { RunStatusBadge } from "./run-status-badge";

declare module "@tanstack/react-table" {
	interface ColumnMeta<TData extends RowData, TValue> {
		align?: "left" | "right" | "center";
		className?: string;
	}
}

const runColumns: ColumnDef<PayrollRunListItem>[] = [
	{
		id: "period",
		header: "Period",
		cell: ({ row }) => periodLabel(row.original.period_year, row.original.period_month),
	},
	{
		accessorKey: "run_type",
		header: "Run Type",
		cell: ({ row }) => runTypeLabel(row.original.run_type),
	},
	{
		accessorKey: "status",
		header: "Status",
		cell: ({ row }) => <RunStatusBadge status={row.original.status} />,
	},
];

export default function PayRunsPage() {
	const navigate = useNavigate();
	const { hasCapability } = useAuth();
	const canCreateRun = hasCapability("create_run");

	const [createPeriodOpen, setCreatePeriodOpen] = useState(false);
	const [createRunOpen, setCreateRunOpen] = useState(false);

	const periodsQuery = usePayrollPeriods();
	const runsQuery = usePayrollRuns();

	const periods = periodsQuery.data ?? [];
	const runs = runsQuery.data ?? [];

	const table = useReactTable({
		data: runs,
		columns: runColumns,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.id,
	});

	const runsEmpty = !runsQuery.isLoading && runs.length === 0;

	return (
		<CapabilityGate capability="create_run" title="Pay Runs">
			<AppLayout
				title="Pay Runs"
				actions={
					canCreateRun ? (
						<div className="flex flex-wrap items-center gap-2">
							<Button size="xs" variant="outline" onClick={() => setCreatePeriodOpen(true)}>
								Period
							</Button>
							<Button size="xs" onClick={() => setCreateRunOpen(true)}>
								Add
							</Button>
						</div>
					) : undefined
				}
			>
				<PageShell data-testid="pay-runs-page">
					<PageSection className="grid gap-3">
						<div className="flex flex-wrap items-center justify-between gap-2">
							<h2 className="text-sm font-medium">Payroll Periods</h2>
						</div>

						{periodsQuery.isLoading ? <DataTableSkeleton rows={3} /> : null}

						{periodsQuery.isError ? (
							<ErrorWithRetry
								message={getErrorMessage(periodsQuery.error, "Failed to load payroll periods.")}
								onRetry={() => void periodsQuery.refetch()}
							/>
						) : null}

						{!periodsQuery.isLoading && !periodsQuery.isError && periods.length === 0 ? (
							<p className="text-sm text-muted-foreground">No payroll periods yet.</p>
						) : null}

						{!periodsQuery.isLoading && !periodsQuery.isError && periods.length > 0 ? (
							<ul className="flex flex-wrap gap-2" data-testid="payroll-periods-list">
								{periods.map((period: PayrollPeriodResponse) => (
									<li key={period.id}>
										<Badge variant="secondary">
											{periodLabel(period.period_year, period.period_month)}
										</Badge>
									</li>
								))}
							</ul>
						) : null}
					</PageSection>

					<PageSection className="grid gap-3">
						<div className="flex flex-wrap items-center justify-between gap-2">
							<h2 className="text-sm font-medium">Pay Runs</h2>
						</div>

						{runsQuery.isLoading ? <DataTableSkeleton /> : null}

						{runsQuery.isError ? (
							<ErrorWithRetry
								message={getErrorMessage(runsQuery.error, "Failed to load pay runs.")}
								onRetry={() => void runsQuery.refetch()}
							/>
						) : null}

						{!runsQuery.isLoading && !runsQuery.isError && runsEmpty ? (
							<EmptyState
								icon={WalletCards}
								title="No pay runs"
								description="Create a period and pay run to get started."
							/>
						) : null}

						{!runsQuery.isLoading && !runsQuery.isError && !runsEmpty ? (
							<DataTableShell
								table={table}
								onRowClick={(row) => void navigate(`/pay-runs/${row.id}`)}
								getRowAriaLabel={(row) =>
									`Open pay run ${periodLabel(row.period_year, row.period_month)}, ${runTypeLabel(row.run_type)}`
								}
							/>
						) : null}
					</PageSection>
				</PageShell>

				{canCreateRun && createPeriodOpen ? (
					<CreatePeriodDialog open={createPeriodOpen} onOpenChange={setCreatePeriodOpen} />
				) : null}
				{canCreateRun && createRunOpen ? (
					<CreateRunDialog open={createRunOpen} onOpenChange={setCreateRunOpen} />
				) : null}
			</AppLayout>
		</CapabilityGate>
	);
}
