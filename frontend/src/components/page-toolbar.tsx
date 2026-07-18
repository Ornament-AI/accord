import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface PageToolbarProps {
	children: ReactNode;
	trailing?: ReactNode;
	className?: string;
	trailingClassName?: string;
}

export function PageToolbar({
	children,
	trailing,
	className,
	trailingClassName,
}: PageToolbarProps) {
	return (
		<div className={cn("flex flex-wrap items-center gap-2", className)}>
			{children}
			{trailing ? (
				<div className={cn("flex flex-none items-center gap-2", trailingClassName)}>{trailing}</div>
			) : null}
		</div>
	);
}
