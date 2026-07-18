import {
	type ColumnDef,
	getCoreRowModel,
	type RowData,
	useReactTable,
} from "@tanstack/react-table";
import { Pencil, Plus, Wallet } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
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

type PayComponentsPageProps = {
	canManage: boolean;
	onEdit: (component: PayComponentResponse) => void;
};

function buildColumns({
	canManage,
	onEdit,
}: PayComponentsPageProps): ColumnDef<PayComponentResponse>[] {
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
		{
			accessorKey: "display_order",
			header: "Display order",
			meta: { align: "right" },
		},
	];

	if (canManage) {
		columns.push({
			id: "actions",
			header: "Actions",
			cell: ({ row }) => (
				<Button
					type="button"
					size="sm"
					variant="ghost"
					aria-label={`Edit ${row.original.code}`}
					onClick={(event) => {
						event.stopPropagation();
						onEdit(row.original);
					}}
				>
					<Pencil className="size-4" />
					Edit
				</Button>
			),
		});
	}

	return columns;
}

export default function PayComponentsPage() {
	const navigate = useNavigate();
	const { hasCapability } = useAuth();
	const canManage = hasCapability("manage_master_data");

	const [createOpen, setCreateOpen] = useState(false);
	const [editOpen, setEditOpen] = useState(false);
	const [editing, setEditing] = useState<PayComponentResponse | null>(null);

	const listQuery = usePayComponentsList();

	const columns = buildColumns({
		canManage,
		onEdit: (component) => {
			setEditing(component);
			setEditOpen(true);
		},
	});

	const table = useReactTable({
		data: listQuery.data ?? [],
		columns,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.id,
	});

	const isEmpty = !listQuery.isLoading && (listQuery.data?.length ?? 0) === 0;

	return (
		<CapabilityGate capability="view_master_data" title="Pay components">
			<AppLayout
				title="Pay components"
				actions={
					canManage ? (
						<Button size="sm" onClick={() => setCreateOpen(true)}>
							<Plus className="size-4" />
							New pay component
						</Button>
					) : undefined
				}
			>
				<PageShell data-testid="pay-components-page">
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
							title="No pay components"
							description="Create a pay component to get started."
						>
							{canManage ? (
								<Button size="sm" onClick={() => setCreateOpen(true)}>
									<Plus className="size-4" />
									New pay component
								</Button>
							) : null}
						</EmptyState>
					) : null}

					{!listQuery.isLoading && !listQuery.isError && !isEmpty ? (
						<DataTableShell
							table={table}
							onRowClick={(row) => void navigate(`/pay-components/${row.id}`)}
							getRowAriaLabel={(row) => `Open pay component ${row.code}, ${row.name}`}
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
