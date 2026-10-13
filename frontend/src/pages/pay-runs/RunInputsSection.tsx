import { type ColumnDef, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTableShell } from "@/components/data-table-shell";
import { EmptyState } from "@/components/empty-state";
import { PageSection } from "@/components/page-shell";
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
import {
	type PayrollRunInputResponse,
	useDeletePayrollRunInput,
	usePayrollRunInputs,
	usePayrollRunRoster,
} from "@/lib/api/payroll-runs";
import { getErrorMessage } from "@/lib/errors";
import { formatCanonicalMoney, inputKindLabel } from "@/lib/payroll-display";
import { formatDate } from "@/lib/utils";

type RunInputsSectionProps = {
	runId: string;
	/** When true, Edit/Delete affordances render (draft run + create_run). */
	editable: boolean;
	onEdit: (input: PayrollRunInputResponse) => void;
};

export function RunInputsSection({ runId, editable, onEdit }: RunInputsSectionProps) {
	const inputsQuery = usePayrollRunInputs(runId);
	const rosterQuery = usePayrollRunRoster(runId);
	const deleteMutation = useDeletePayrollRunInput(runId);
	const [deleting, setDeleting] = useState<PayrollRunInputResponse | null>(null);

	const employeeLabelById = useMemo(() => {
		const map = new Map<string, string>();
		for (const row of rosterQuery.data ?? []) {
			map.set(row.employee_id, row.employee_name?.trim() || row.employee_number);
		}
		return map;
	}, [rosterQuery.data]);

	const columns = useMemo<ColumnDef<PayrollRunInputResponse>[]>(
		() => [
			{
				accessorKey: "employee_id",
				header: "Employee",
				cell: ({ row }) =>
					employeeLabelById.get(row.original.employee_id) ?? row.original.employee_id,
			},
			{ accessorKey: "component_code", header: "Component" },
			{
				accessorKey: "input_kind",
				header: "Kind",
				cell: ({ row }) => inputKindLabel(row.original.input_kind),
			},
			{
				id: "value",
				header: "Value",
				cell: ({ row }) =>
					row.original.amount != null
						? formatCanonicalMoney(row.original.amount)
						: row.original.rate != null
							? `Rate ${row.original.rate}`
							: "—",
				meta: { align: "right" },
			},
			{
				id: "service_period",
				header: "Service Period",
				cell: ({ row }) =>
					row.original.service_period_start && row.original.service_period_end
						? `${formatDate(row.original.service_period_start)} – ${formatDate(
								row.original.service_period_end,
							)}`
						: "—",
			},
			{ accessorKey: "reason", header: "Reason" },
			...(editable
				? [
						{
							id: "actions",
							header: "",
							cell: ({ row }: { row: { original: PayrollRunInputResponse } }) => (
								<div className="flex justify-end gap-1">
									<Button
										size="xs"
										variant="outline"
										onClick={() => onEdit(row.original)}
										aria-label={`Edit input ${row.original.component_code}`}
									>
										Edit
									</Button>
									<Button
										size="xs"
										variant="outline"
										onClick={() => setDeleting(row.original)}
										aria-label={`Delete input ${row.original.component_code}`}
									>
										Delete
									</Button>
								</div>
							),
						} satisfies ColumnDef<PayrollRunInputResponse>,
					]
				: []),
		],
		[editable, employeeLabelById, onEdit],
	);

	const table = useReactTable({
		data: inputsQuery.data ?? [],
		columns,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.id,
	});

	const handleDelete = async () => {
		if (!deleting) return;
		try {
			await deleteMutation.mutateAsync(deleting.id);
			toast.success("Run input deleted");
			setDeleting(null);
		} catch (error) {
			toast.error(getErrorMessage(error, "Failed to delete run input."));
		}
	};

	const inputs = inputsQuery.data ?? [];
	// Collapse only an empty read-only section — a failed read must surface its
	// retry affordance to every role, not vanish silently.
	if (!editable && !inputsQuery.isLoading && !inputsQuery.isError && inputs.length === 0) {
		return null;
	}

	return (
		<PageSection className="gap-3" data-testid="run-inputs-section">
			<h2 className="text-base font-semibold">Run Inputs</h2>

			{inputsQuery.isLoading ? <PageSkeleton /> : null}

			{inputsQuery.isError ? (
				<ErrorWithRetry
					message={getErrorMessage(inputsQuery.error, "Failed to load run inputs.")}
					onRetry={() => void inputsQuery.refetch()}
				/>
			) : null}

			{!inputsQuery.isLoading && !inputsQuery.isError && inputs.length === 0 ? (
				<EmptyState
					title="No Run Inputs"
					description="Exceptions, overrides, and one-time inputs appear here."
				/>
			) : null}

			{!inputsQuery.isLoading && !inputsQuery.isError && inputs.length > 0 ? (
				<DataTableShell table={table} tableClassName="min-w-[48rem]" />
			) : null}

			<Dialog open={deleting != null} onOpenChange={(open) => !open && setDeleting(null)}>
				<DialogContent>
					<DialogHeader className="px-6 pt-5 pb-3">
						<DialogTitle>Delete run input?</DialogTitle>
						<DialogDescription>
							Remove the {deleting?.component_code}{" "}
							{deleting ? inputKindLabel(deleting.input_kind) : ""} input for{" "}
							{deleting ? (employeeLabelById.get(deleting.employee_id) ?? "this employee") : ""}.
							This cannot be undone.
						</DialogDescription>
					</DialogHeader>
					<DialogBody className="pb-2" />
					<DialogFooter className="border-t px-6 py-4">
						<Button
							variant="outline"
							onClick={() => setDeleting(null)}
							disabled={deleteMutation.isPending}
						>
							Cancel
						</Button>
						<Button
							variant="destructive"
							onClick={() => void handleDelete()}
							disabled={deleteMutation.isPending}
						>
							{deleteMutation.isPending ? "Deleting…" : "Delete"}
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</PageSection>
	);
}
