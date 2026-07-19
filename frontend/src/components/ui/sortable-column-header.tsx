import { ArrowDownIcon as ArrowDown } from "@phosphor-icons/react/dist/csr/ArrowDown";
import { ArrowUpIcon as ArrowUp } from "@phosphor-icons/react/dist/csr/ArrowUp";
import type { Column } from "@tanstack/react-table";

import { cn } from "@/lib/utils";

interface SortableColumnHeaderProps<T> {
	column: Column<T, unknown>;
	label: string;
}

export function SortableColumnHeader<T>({ column, label }: SortableColumnHeaderProps<T>) {
	const sorted = column.getIsSorted();
	return (
		<button
			type="button"
			className={cn(
				"-ml-1 inline-flex items-center gap-0.5 rounded-sm px-1 py-0.5 text-left outline-none hover:bg-muted/80 focus-visible:ring-2 focus-visible:ring-ring/35",
				sorted ? "text-foreground" : "text-muted-foreground",
			)}
			onClick={column.getToggleSortingHandler()}
			disabled={!column.getCanSort()}
			aria-label={
				sorted === "asc"
					? `Sorted by ${label}, ascending. Click to sort descending.`
					: sorted === "desc"
						? `Sorted by ${label}, descending. Click to sort ascending.`
						: `Sort by ${label}`
			}
		>
			<span>{label}</span>
			{sorted === "asc" ? (
				<ArrowUp className="size-3.5 shrink-0 opacity-70" aria-hidden />
			) : sorted === "desc" ? (
				<ArrowDown className="size-3.5 shrink-0 opacity-70" aria-hidden />
			) : null}
		</button>
	);
}
