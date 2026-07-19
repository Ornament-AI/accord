import { ColumnsIcon as Columns3 } from "@phosphor-icons/react/dist/csr/Columns";
import type { RowData, Table as TanstackTable, VisibilityState } from "@tanstack/react-table";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { toolbarOutlineClassName } from "@/components/ui/button-variants";
import { Checkbox } from "@/components/ui/checkbox";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

declare module "@tanstack/react-table" {
	interface ColumnMeta<TData extends RowData, TValue> {
		align?: "left" | "right" | "center";
		className?: string;
		/** Human-readable label used when `header` is a React node (e.g. sortable headers). */
		label?: string;
		/** Hide this column from the user-facing Columns menu while preserving table data. */
		hideFromColumnVisibilityToggle?: boolean;
	}
}

/* ------------------------------------------------------------------ */
/*  Hook: localStorage-persisted column visibility state               */
/* ------------------------------------------------------------------ */
export function usePersistedColumnVisibility(
	key: string,
	defaultVisibility: VisibilityState,
): [VisibilityState, React.Dispatch<React.SetStateAction<VisibilityState>>] {
	const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(() => {
		try {
			const stored = localStorage.getItem(key);
			if (stored) return JSON.parse(stored) as VisibilityState;
		} catch (error) {
			console.warn("Failed to read persisted column visibility.", { key, error });
		}
		return defaultVisibility;
	});

	useEffect(() => {
		try {
			localStorage.setItem(key, JSON.stringify(columnVisibility));
		} catch (error) {
			console.warn("Failed to persist column visibility.", { key, error });
		}
	}, [key, columnVisibility]);

	return [columnVisibility, setColumnVisibility];
}

/* ------------------------------------------------------------------ */
/*  Component: column visibility popover toggle                        */
/* ------------------------------------------------------------------ */
interface ColumnVisibilityToggleProps<TData> {
	table: TanstackTable<TData>;
	iconOnly?: boolean;
	triggerClassName?: string;
}

export function ColumnVisibilityToggle<TData>({
	iconOnly = false,
	table,
	triggerClassName,
}: ColumnVisibilityToggleProps<TData>) {
	const hideableColumns = table
		.getAllLeafColumns()
		.filter(
			(column) => column.getCanHide() && !column.columnDef.meta?.hideFromColumnVisibilityToggle,
		);

	return (
		<Popover>
			<PopoverTrigger
				render={
					<Button
						variant="outline"
						size={iconOnly ? "icon" : "default"}
						aria-label={iconOnly ? "Columns" : undefined}
						title={iconOnly ? "Columns" : undefined}
						className={cn(toolbarOutlineClassName, triggerClassName)}
					>
						<Columns3 className="size-4 text-muted-foreground" />
						<span className={iconOnly ? "sr-only" : undefined}>Columns</span>
					</Button>
				}
			/>
			<PopoverContent align="end" className="w-56 overflow-hidden p-0">
				<div className="app-scrollbar max-h-96 overflow-y-auto scroll-fade p-1.5">
					<div className="flex flex-col gap-0.5">
						{hideableColumns.map((column) => {
							const header = column.columnDef.header;
							const columnLabel =
								column.columnDef.meta?.label ?? (typeof header === "string" ? header : column.id);

							return (
								// Base UI renders the visually hidden native checkbox inside this label.
								// biome-ignore lint/a11y/noLabelWithoutControl: the input is injected by CheckboxPrimitive.Root
								<label
									key={column.id}
									className="group flex min-h-10 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm transition-colors hover:bg-muted/60 focus-within:bg-muted/60"
								>
									<Checkbox
										aria-label={`Toggle ${columnLabel} column`}
										checked={column.getIsVisible()}
										className="size-[1.125rem] rounded-[5px]"
										onCheckedChange={(checked) => column.toggleVisibility(!!checked)}
									/>
									<span
										aria-hidden="true"
										className="select-none text-foreground/90 group-hover:text-foreground"
									>
										{columnLabel}
									</span>
								</label>
							);
						})}
					</div>
				</div>
			</PopoverContent>
		</Popover>
	);
}
