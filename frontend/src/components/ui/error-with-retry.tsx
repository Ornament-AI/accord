import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ErrorWithRetryProps {
	message?: string;
	onRetry: () => void;
	className?: string;
}

function ErrorWithRetry({
	message = "Failed to load data.",
	onRetry,
	className,
}: ErrorWithRetryProps) {
	return (
		<div className={cn("flex flex-col items-center justify-center gap-4 p-8", className)}>
			<p className="text-destructive text-sm">{message}</p>
			<Button variant="outline" size="sm" onClick={onRetry}>
				Retry
			</Button>
		</div>
	);
}

export { ErrorWithRetry };
