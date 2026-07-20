import { WalletIcon as Wallet } from "@phosphor-icons/react/dist/csr/Wallet";
import {
	type ColumnDef,
	getCoreRowModel,
	type RowData,
	useReactTable,
} from "@tanstack/react-table";
import { useState } from "react";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import {
	ColumnVisibilityToggle,
	usePersistedColumnVisibility,
} from "@/components/column-visibility";
import { DataTableShell } from "@/components/data-table-shell";
import { DataTableSkeleton } from "@/components/data-table-skeleton";
import { EmptyState } from "@/components/empty-state";
import { PageShell } from "@/components/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { useAuth } from "@/contexts/AuthContext";
import {
	classificationLabel,
	type PayComponentResponse,
	usePayComponentsList,
} from "@/lib/api/pay-setup";
import { getErrorMessage } from "@/lib/errors";

import { CreatePayComponentDialog } from "./CreatePayComponentDialog";
import { EditPayComponentDialog } from "./EditPayComponentDialog";

declare module "@tanstack/react-table" {
	interface ColumnMeta<TData extends RowData, TValue> {
		align?: "left" | "right" | "center";
		className?: string;
	}
}

const columns: ColumnDef<PayComponentResponse>[] = [
	{
		accessorKey: "code",
		header: "Code",
	},
	{
		accessorKey: "name",
		header: "Name",
	},
	{
		accessorKey: "classification",
		header: "Classification",
		cell: ({ row }) => (
			<Badge variant="secondary">{classificationLabel(row.original.classification)}</Badge>
		),
	},
	{
		accessorKey: "is_active",
		header: "Active",
		cell: ({ row }) => (row.original.is_active ? "Yes" : "No"),
	},
];

export default function PayComponentsPage() {
	const { hasCapability } = useAuth();
	const canManage = hasCapability("manage_master_data");

	const [createOpen, setCreateOpen] = useState(false);
	const [editOpen, setEditOpen] = useState(false);
	const [editing, setEditing] = useState<PayComponentResponse | null>(null);

	const [columnVisibility, setColumnVisibility] = usePersistedColumnVisibility(
		"accord:pay-components:columns",
		{ code: false },
	);

	const listQuery = usePayComponentsList();

	const table = useReactTable({
		data: listQuery.data ?? [],
		columns,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.id,
		state: { columnVisibility },
		onColumnVisibilityChange: setColumnVisibility,
	});

	const isEmpty = !listQuery.isLoading && (listQuery.data?.length ?? 0) === 0;

	const openEdit = (component: PayComponentResponse) => {
		setEditing(component);
		setEditOpen(true);
	};

	return (
		<CapabilityGate capability="view_master_data" title="Pay Components">
			<AppLayout
				title="Pay Components"
				actions={
					canManage ? (
						<Button size="xs" onClick={() => setCreateOpen(true)}>
							Add
						</Button>
					) : undefined
				}
			>
				<PageShell data-testid="pay-components-page">
					<div className="flex flex-wrap items-center justify-end gap-2">
						<ColumnVisibilityToggle table={table} iconOnly triggerClassName="justify-center" />
					</div>

					{listQuery.isLoading ? <DataTableSkeleton /> : null}

					{listQuery.isError ? (
						<ErrorWithRetry
							message={getErrorMessage(listQuery.error, "Failed to load pay components.")}
							onRetry={() => void listQuery.refetch()}
						/>
					) : null}

					{!listQuery.isLoading && !listQuery.isError && isEmpty ? (
						<EmptyState
							icon={Wallet}
							title="No Pay Components"
							description="Create a pay component to get started."
						/>
					) : null}

					{!listQuery.isLoading && !listQuery.isError && !isEmpty ? (
						<DataTableShell
							table={table}
							onRowClick={canManage ? openEdit : undefined}
							getRowAriaLabel={(row) => `Edit Pay Component ${row.code}`}
						/>
					) : null}
				</PageShell>

				{canManage ? (
					<>
						<CreatePayComponentDialog open={createOpen} onOpenChange={setCreateOpen} />
						<EditPayComponentDialog
							open={editOpen}
							onOpenChange={(open) => {
								setEditOpen(open);
								if (!open) setEditing(null);
							}}
							component={editing}
						/>
					</>
				) : null}
			</AppLayout>
		</CapabilityGate>
	);
}
