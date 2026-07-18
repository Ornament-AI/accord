import { Skeleton } from "@/components/ui/skeleton";

export function LoadingState({ fullScreen = true }: { fullScreen?: boolean }) {
	return (
		<div className={`p-4 md:p-6 ${fullScreen ? "h-screen" : "flex-1"}`}>
			<output aria-live="polite" aria-busy="true" className="block h-full min-h-64">
				<Skeleton className="h-full w-full" />
				<span className="sr-only">Loading&hellip;</span>
			</output>
		</div>
	);
}
