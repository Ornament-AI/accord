import { UsersThreeIcon as Users } from "@phosphor-icons/react/dist/csr/UsersThree";
import {
	type ColumnDef,
	getCoreRowModel,
	type RowData,
	useReactTable,
} from "@tanstack/react-table";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import {
	ColumnVisibilityToggle,
	usePersistedColumnVisibility,
} from "@/components/column-visibility";
import { DataSearchControl } from "@/components/data-search-control";
import { DataTableShell } from "@/components/data-table-shell";
import { EmptyState } from "@/components/empty-state";
import { PageShell } from "@/components/page-shell";
import { PageSkeleton } from "@/components/page-skeleton";
import { PageToolbar } from "@/components/page-toolbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { useAuth } from "@/contexts/AuthContext";
import { type EmployeeSummary, useEmployeesList } from "@/lib/api/employees";
import { parseApiDate, toApiDate, todayApiDate } from "@/lib/calendar-date";
import { getErrorMessage } from "@/lib/errors";

import { CreateEmployeeDialog } from "./CreateEmployeeDialog";

declare module "@tanstack/react-table" {
	interface ColumnMeta<TData extends RowData, TValue> {
		align?: "left" | "right" | "center";
		className?: string;
	}
}

function regimeLabel(regime: string | null | undefined): string {
	if (!regime) return "—";
	return regime.toUpperCase();
}

const columns: ColumnDef<EmployeeSummary>[] = [
	{
		accessorKey: "employee_number",
		header: "Employee Number",
	},
	{
		accessorKey: "name",
		header: "Name",
		cell: ({ row }) => row.original.name ?? "—",
	},
	{
		id: "designation",
		header: "Designation",
		cell: () => "—",
	},
	{
		accessorKey: "retirement_regime",
		header: "Regime",
		cell: ({ row }) => {
			const regime = row.original.retirement_regime;
			if (!regime) return "—";
			return <Badge variant="secondary">{regimeLabel(regime)}</Badge>;
		},
	},
	{
		id: "pan",
		header: "PAN",
		// EmployeeSummary in api.generated.ts does not include PAN (list endpoint omits sensitive fields).
		cell: () => "—",
	},
];

function useDebouncedValue<T>(value: T, delayMs: number): T {
	const [debounced, setDebounced] = useState(value);
	useEffect(() => {
		const handle = window.setTimeout(() => setDebounced(value), delayMs);
		return () => window.clearTimeout(handle);
	}, [value, delayMs]);
	return debounced;
}

export default function EmployeeListPage() {
	const navigate = useNavigate();
	const { hasCapability } = useAuth();
	const canManage = hasCapability("manage_master_data");

	const [asOf, setAsOf] = useState(() => todayApiDate());
	const [search, setSearch] = useState("");
	const debouncedSearch = useDebouncedValue(search, 300);
	const [page, setPage] = useState(1);
	const [createOpen, setCreateOpen] = useState(false);
	const [columnVisibility, setColumnVisibility] = usePersistedColumnVisibility(
		"accord:employees:columns",
		{},
	);

	const listQuery = useEmployeesList({
		as_of: asOf,
		search: debouncedSearch.trim() || null,
		page,
		size: 20,
	});

	const table = useReactTable({
		data: listQuery.data?.items ?? [],
		columns,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.id,
		state: { columnVisibility },
		onColumnVisibilityChange: setColumnVisibility,
	});

	const asOfDate = useMemo(() => parseApiDate(asOf), [asOf]);
	const totalPages = listQuery.data?.total_pages ?? 1;
	const isEmpty = !listQuery.isLoading && (listQuery.data?.items.length ?? 0) === 0;

	return (
		<CapabilityGate capability="view_master_data" title="Employees">
			<AppLayout
				title="Employees"
				actions={
					canManage ? (
						<Button size="xs" onClick={() => setCreateOpen(true)}>
							Add
						</Button>
					) : undefined
				}
			>
				<PageShell data-testid="employee-list-page">
					{listQuery.isLoading ? <PageSkeleton /> : null}

					{listQuery.isError ? (
						<ErrorWithRetry
							message={getErrorMessage(listQuery.error, "Failed to load employees.")}
							onRetry={() => void listQuery.refetch()}
						/>
					) : null}

					{!listQuery.isLoading && !listQuery.isError ? (
						<>
							<PageToolbar
								trailing={
									<ColumnVisibilityToggle
										table={table}
										iconOnly
										triggerClassName="justify-center"
									/>
								}
							>
								<DataSearchControl
									search={search || undefined}
									title="Search Employees"
									placeholder="Employee Number or Name…"
									onSearchChange={(next) => {
										setSearch(next ?? "");
										setPage(1);
									}}
								/>
								<DatePicker
									value={asOfDate}
									onValueChange={(date) => {
										if (date) {
											setAsOf(toApiDate(date));
											setPage(1);
										}
									}}
									aria-label="As of Date"
									placeholder="As of"
								/>
							</PageToolbar>

							{isEmpty ? (
								<EmptyState
									icon={Users}
									title="No Employees Found"
									description={
										search.trim()
											? "Try a different search term or as-of date."
											: "Create an employee to get started."
									}
								/>
							) : (
								<DataTableShell
									table={table}
									isPlaceholderData={listQuery.isPlaceholderData}
									page={page}
									totalPages={totalPages}
									onPageChange={setPage}
									onRowClick={(row) => void navigate(`/employees/${row.id}`)}
									getRowAriaLabel={(row) =>
										`Open employee ${row.employee_number}${row.name ? `, ${row.name}` : ""}`
									}
								/>
							)}
						</>
					) : null}
				</PageShell>

				{canManage ? <CreateEmployeeDialog open={createOpen} onOpenChange={setCreateOpen} /> : null}
			</AppLayout>
		</CapabilityGate>
	);
}
