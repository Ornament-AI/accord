import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface PageSkeletonProps {
	fullScreen?: boolean;
	className?: string;
}

/** Shared page loading surface: one large muted block. */
export function PageSkeleton({ fullScreen = false, className }: PageSkeletonProps) {
	return (
		<div
			data-slot="page-skeleton"
			className={cn(
				"flex min-h-0 min-w-0 flex-1 flex-col",
				fullScreen ? "h-screen p-4 md:py-6 lg:px-6" : null,
				className,
			)}
		>
			<output aria-live="polite" aria-busy="true" className="flex min-h-64 flex-1 flex-col">
				<Skeleton className="min-h-64 w-full flex-1 rounded-lg" />
				<span className="sr-only">Loading&hellip;</span>
			</output>
		</div>
	);
}
