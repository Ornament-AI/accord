import { MoneyIcon as WalletCards } from "@phosphor-icons/react/dist/csr/Money";
import {
	type ColumnDef,
	getCoreRowModel,
	type RowData,
	useReactTable,
} from "@tanstack/react-table";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { DataTableShell } from "@/components/data-table-shell";
import { EmptyState } from "@/components/empty-state";
import { PageSection, PageShell } from "@/components/page-shell";
import { PageSkeleton } from "@/components/page-skeleton";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogBody,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Label } from "@/components/ui/label";
import { MonthPicker } from "@/components/ui/month-picker";
import { useAuth } from "@/contexts/AuthContext";
import {
	type PayrollRunListItem,
	periodLabel,
	useCreatePayrollPeriod,
	useCreatePayrollRun,
	usePayrollPeriods,
	usePayrollRuns,
} from "@/lib/api/payroll-runs";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { getErrorMessage } from "@/lib/errors";

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
		accessorKey: "status",
		header: "Status",
		cell: ({ row }) => <RunStatusBadge status={row.original.status} />,
	},
];

export default function PayRunsPage() {
	const navigate = useNavigate();
	const { hasCapability } = useAuth();
	const canCreateRun = hasCapability("create_run");

	const [createOpen, setCreateOpen] = useState(false);
	const [selectedPeriod, setSelectedPeriod] = useState("");

	const periodsQuery = usePayrollPeriods();
	const runsQuery = usePayrollRuns();
	const createPeriod = useCreatePayrollPeriod();
	const createRun = useCreatePayrollRun();

	const runs = runsQuery.data ?? [];

	const table = useReactTable({
		data: runs,
		columns: runColumns,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.id,
	});

	const runsEmpty = !runsQuery.isLoading && runs.length === 0;
	const isStarting = createPeriod.isPending || createRun.isPending;
	const handleCreateOpenChange = (open: boolean) => {
		setCreateOpen(open);
		if (!open && !isStarting) setSelectedPeriod("");
	};

	const handleStartPayroll = async (event: FormEvent) => {
		event.preventDefault();
		const [yearText, monthText] = selectedPeriod.split("-");
		const year = Number(yearText);
		const month = Number(monthText);
		if (!Number.isInteger(year) || !Number.isInteger(month)) {
			toast.error("Choose a payroll period first.");
			return;
		}
		try {
			let period = (periodsQuery.data ?? []).find(
				(item) => item.period_year === year && item.period_month === month,
			);
			period ??= await createPeriod.mutateAsync({ period_year: year, period_month: month });
			let run = runs.find((item) => item.period_id === period.id);
			run ??= await createRun.mutateAsync({ period_id: period.id });
			setCreateOpen(false);
			setSelectedPeriod("");
			void navigate(`/pay-runs/${run.id}`);
		} catch (error) {
			toast.error(getErrorMessage(error, "Unable to start payroll for this period."));
		}
	};

	return (
		<CapabilityGate capability="create_run" title="Pay Runs">
			<AppLayout
				title="Pay Runs"
				actions={
					canCreateRun ? (
						<Button size="xs" onClick={() => setCreateOpen(true)}>
							Add
						</Button>
					) : undefined
				}
			>
				<PageShell data-testid="pay-runs-page">
					<PageSection className="gap-3">
						{runsQuery.isLoading ? <PageSkeleton /> : null}

						{runsQuery.isError ? (
							<ErrorWithRetry
								message={getErrorMessage(runsQuery.error, "Failed to load pay runs.")}
								onRetry={() => void runsQuery.refetch()}
							/>
						) : null}

						{!runsQuery.isLoading && !runsQuery.isError && runsEmpty ? (
							<EmptyState
								icon={WalletCards}
								title="No Payroll History"
								description="Select Add to create the first payroll run."
							/>
						) : null}

						{!runsQuery.isLoading && !runsQuery.isError && !runsEmpty ? (
							<DataTableShell
								table={table}
								onRowClick={(row) => void navigate(`/pay-runs/${row.id}`)}
								getRowAriaLabel={(row) =>
									`Open pay run ${periodLabel(row.period_year, row.period_month)}`
								}
							/>
						) : null}
					</PageSection>
				</PageShell>

				{canCreateRun ? (
					<Dialog open={createOpen} onOpenChange={handleCreateOpenChange}>
						<DialogContent className={DIALOG_CONTENT_CLASSNAMES.compactForm}>
							<DialogHeader className="px-6 pt-5 pb-3">
								<DialogTitle>Add Pay Run</DialogTitle>
								<DialogDescription>
									Choose the payroll month to open it or create a new draft.
								</DialogDescription>
							</DialogHeader>

							<form
								className="flex min-h-0 flex-1 flex-col"
								onSubmit={(event) => void handleStartPayroll(event)}
							>
								<DialogBody className="pb-8">
									<div className="grid gap-2">
										<Label htmlFor="pay-run-month">Payroll Month</Label>
										<MonthPicker
											id="pay-run-month"
											value={selectedPeriod}
											onChange={setSelectedPeriod}
											placeholder="Choose payroll month"
											ariaLabel="Payroll Month"
											disabled={isStarting}
											className="h-11 w-full"
										/>
									</div>
								</DialogBody>

								<DialogFooter className="border-t px-6 py-4">
									<Button
										type="button"
										variant="outline"
										onClick={() => handleCreateOpenChange(false)}
										disabled={isStarting}
									>
										Cancel
									</Button>
									<Button type="submit" disabled={!selectedPeriod || isStarting}>
										{isStarting ? "Opening…" : "Continue"}
									</Button>
								</DialogFooter>
							</form>
						</DialogContent>
					</Dialog>
				) : null}
			</AppLayout>
		</CapabilityGate>
	);
}
