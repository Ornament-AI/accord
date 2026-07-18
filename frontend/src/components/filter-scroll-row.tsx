import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface FilterScrollRowProps {
	children: ReactNode;
	className?: string;
}

/**
 * Horizontally-scrolling filter row with a scroll-aware edge fade. Controls keep
 * their own sizing; when they overflow, the row scrolls instead of shrinking.
 */
export function FilterScrollRow({ children, className }: FilterScrollRowProps) {
	return (
		<div
			className={cn(
				// p-1/-m-1: interior breathing room so focus rings (3px box-shadow) aren't
				// sheared by overflow/mask clipping; negative margin keeps layout neutral.
				"scroll-fade-x no-scrollbar -m-1 flex min-w-0 flex-1 items-center gap-2 overflow-x-auto p-1",
				className,
			)}
		>
			{children}
		</div>
	);
}
