import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Grid container for {@link DataEntryField}s. Lays out fields in responsive
 * columns and leaves row tracks implicit so each field's two-row subgrid can
 * share them, keeping every control aligned across a row.
 */
type DataEntryFieldGridColumns = 2 | 3 | "responsive";

type DataEntryFieldGridProps = {
	children: ReactNode;
	columns?: DataEntryFieldGridColumns;
	className?: string;
};

const COLUMN_CLASSES: Record<DataEntryFieldGridColumns, string> = {
	2: "md:grid-cols-2",
	3: "md:grid-cols-3",
	responsive: "sm:grid-cols-2 lg:grid-cols-3",
};

export function DataEntryFieldGrid({ children, columns = 3, className }: DataEntryFieldGridProps) {
	return (
		<div className={cn("grid gap-x-4 gap-y-5", COLUMN_CLASSES[columns], className)}>{children}</div>
	);
}
