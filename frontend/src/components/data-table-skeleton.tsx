import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface DataTableSkeletonProps {
	rows?: number;
	className?: string;
}

export function DataTableSkeleton({ rows = 8, className }: DataTableSkeletonProps) {
	const rowKeys = Array.from(
		{ length: rows },
		(_, rowNumber) => `data-table-skeleton-${rowNumber}`,
	);

	return (
		<div className={cn("app-table-surface rounded-lg p-3", className)}>
			<div className="flex flex-col gap-3">
				{rowKeys.map((rowKey) => (
					<Skeleton key={rowKey} className="h-11 w-full" />
				))}
			</div>
		</div>
	);
}
