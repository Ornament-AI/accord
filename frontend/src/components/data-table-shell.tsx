import { flexRender, type Row, type Table as TanstackTable } from "@tanstack/react-table";

import { PaginationControls } from "@/components/pagination-controls";
import { isInteractiveRowTarget } from "@/components/table-interactions";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

type DataTableShellProps<TData> = {
	table: TanstackTable<TData>;
	isPlaceholderData?: boolean;
	page?: number;
	totalPages?: number;
	onPageChange?: (page: number) => void;
	/** Extra classes for the inner `<table>`, e.g. `"min-w-[88rem] table-fixed"`. */
	tableClassName?: string;
	/** When provided, rows are clickable; clicks on interactive elements are ignored. */
	onRowClick?: (row: TData) => void;
	getRowAriaLabel?: (row: TData) => string;
	/** Restricts clickability to a subset of rows. Defaults to all rows when `onRowClick` is set. */
	isRowClickable?: (row: TData) => boolean;
};

/**
 * Shared TanStack table shell: app table surface, shared scroll affordance,
 * meta-driven column classes/alignment, guarded row clicks, and pagination.
 */
export function DataTableShell<TData>({
	table,
	isPlaceholderData = false,
	page,
	totalPages,
	onPageChange,
	tableClassName,
	onRowClick,
	getRowAriaLabel,
	isRowClickable,
}: DataTableShellProps<TData>) {
	const rowIsClickable = (row: Row<TData>) =>
		Boolean(onRowClick) && !isPlaceholderData && (isRowClickable?.(row.original) ?? true);
	const activateRow = (row: Row<TData>) => {
		if (!onRowClick || !rowIsClickable(row)) return;
		onRowClick(row.original);
	};

	return (
		<div className="flex flex-col gap-2">
			<div className="app-table-surface overflow-hidden rounded-lg">
				<div className={isPlaceholderData ? "pointer-events-none" : undefined}>
					<Table surface={false} className={tableClassName}>
						<TableHeader>
							{table.getHeaderGroups().map((headerGroup) => (
								<TableRow key={headerGroup.id}>
									{headerGroup.headers.map((header) => (
										<TableHead
											key={header.id}
											className={cn(
												header.column.columnDef.meta?.className,
												header.column.columnDef.meta?.align === "right" && "text-right",
											)}
										>
											{header.isPlaceholder
												? null
												: flexRender(header.column.columnDef.header, header.getContext())}
										</TableHead>
									))}
								</TableRow>
							))}
						</TableHeader>
						<TableBody>
							{table.getRowModel().rows.map((row) => (
								<TableRow
									key={row.id}
									className={rowIsClickable(row) ? "cursor-pointer" : undefined}
									onClick={(event) => {
										if (
											!onRowClick ||
											!rowIsClickable(row) ||
											isInteractiveRowTarget(event.target, event.currentTarget)
										) {
											return;
										}
										activateRow(row);
									}}
								>
									{row.getVisibleCells().map((cell, cellIndex) => (
										<TableCell
											key={cell.id}
											className={cn(
												cell.column.columnDef.meta?.className,
												cell.column.columnDef.meta?.align === "right" && "text-right",
											)}
										>
											{cellIndex === 0 && rowIsClickable(row) ? (
												<button
													type="button"
													className="sr-only focus:not-sr-only focus:mb-1 focus:inline-flex focus:rounded-md focus:bg-background focus:px-2 focus:py-1 focus:ring-2 focus:ring-ring/35"
													onClick={() => activateRow(row)}
												>
													{getRowAriaLabel?.(row.original) ?? "Open row"}
												</button>
											) : null}
											{flexRender(cell.column.columnDef.cell, cell.getContext())}
										</TableCell>
									))}
								</TableRow>
							))}
						</TableBody>
					</Table>
				</div>
			</div>
			{page !== undefined && totalPages !== undefined && onPageChange ? (
				<div className="flex justify-center px-4 py-2">
					<PaginationControls
						page={page}
						totalPages={totalPages}
						disabled={isPlaceholderData}
						onPageChange={onPageChange}
						className="justify-center"
					/>
				</div>
			) : null}
		</div>
	);
}
