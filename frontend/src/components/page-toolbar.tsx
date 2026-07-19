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
		<div
			className={cn(
				"scroll-fade-x no-scrollbar -m-1 flex flex-nowrap items-center gap-2 overflow-x-auto p-1 [&>*]:shrink-0",
				className,
			)}
		>
			{children}
			{trailing ? (
				<div className={cn("flex flex-none items-center gap-2", trailingClassName)}>{trailing}</div>
			) : null}
		</div>
	);
}
