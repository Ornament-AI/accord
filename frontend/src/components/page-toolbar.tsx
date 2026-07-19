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
		<div className={cn("flex items-center justify-between gap-4", className)}>
			<div className="scroll-fade-x no-scrollbar -m-1 flex min-w-0 flex-1 flex-nowrap items-center gap-2 overflow-x-auto p-1 [&>*]:shrink-0">
				{children}
			</div>
			{trailing ? (
				<div className={cn("flex flex-none items-center gap-2", trailingClassName)}>{trailing}</div>
			) : null}
		</div>
	);
}
