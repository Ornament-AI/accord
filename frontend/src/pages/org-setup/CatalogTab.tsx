import {
	type ColumnDef,
	getCoreRowModel,
	type RowData,
	useReactTable,
} from "@tanstack/react-table";
import type { ReactNode } from "react";

import { DataTableShell } from "@/components/data-table-shell";
import { DataTableSkeleton } from "@/components/data-table-skeleton";
import { EmptyState } from "@/components/empty-state";
import { PageToolbar } from "@/components/page-toolbar";
import { Button } from "@/components/ui/button";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { getErrorMessage } from "@/lib/errors";

declare module "@tanstack/react-table" {
	interface ColumnMeta<TData extends RowData, TValue> {
		align?: "left" | "right" | "center";
		className?: string;
	}
}

type CatalogTabProps<T extends { id: string }> = {
	title: string;
	emptyDescription: string;
	icon: React.ComponentType<{ className?: string }>;
	columns: ColumnDef<T, unknown>[];
	data: T[] | undefined;
	isLoading: boolean;
	isError: boolean;
	error: unknown;
	onRetry: () => void;
	canManage: boolean;
	onAdd: () => void;
	onEdit: (row: T) => void;
	toolbar?: ReactNode;
	"data-testid"?: string;
};

export function CatalogTab<T extends { id: string }>({
	title,
	emptyDescription,
	icon: Icon,
	columns,
	data,
	isLoading,
	isError,
	error,
	onRetry,
	canManage,
	onAdd,
	onEdit,
	toolbar,
	"data-testid": testId,
}: CatalogTabProps<T>) {
	const rows = data ?? [];
	const table = useReactTable({
		data: rows,
		columns,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.id,
	});
	const isEmpty = !isLoading && !isError && rows.length === 0;
	const singular = title.endsWith("s") ? title.slice(0, -1) : title;

	return (
		<div className="flex flex-col gap-4" data-testid={testId}>
			{toolbar ? <PageToolbar>{toolbar}</PageToolbar> : null}

			{isLoading ? <DataTableSkeleton /> : null}

			{isError ? (
				<ErrorWithRetry
					message={getErrorMessage(error, `Failed to load ${title.toLowerCase()}.`)}
					onRetry={onRetry}
				/>
			) : null}

			{isEmpty ? (
				<EmptyState icon={Icon} title={`No ${title.toLowerCase()}`} description={emptyDescription}>
					{canManage ? (
						<Button size="xs" onClick={onAdd}>
							Add
						</Button>
					) : null}
				</EmptyState>
			) : null}

			{!isLoading && !isError && !isEmpty ? (
				<DataTableShell
					table={table}
					onRowClick={canManage ? onEdit : undefined}
					getRowAriaLabel={(row) => `Edit ${singular.toLowerCase()} ${row.id}`}
				/>
			) : null}
		</div>
	);
}
