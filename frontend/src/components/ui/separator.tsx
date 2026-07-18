import type * as React from "react";

import { cn } from "@/lib/utils";

interface SeparatorProps extends React.HTMLAttributes<HTMLHRElement> {
	orientation?: "horizontal" | "vertical";
	decorative?: boolean;
}

function Separator({
	className,
	orientation = "horizontal",
	decorative = true,
	...props
}: SeparatorProps) {
	return (
		<hr
			data-slot="separator"
			data-orientation={orientation}
			role={decorative ? "none" : "separator"}
			aria-orientation={decorative ? undefined : orientation}
			className={cn(
				"bg-border border-none shrink-0 data-[orientation=horizontal]:h-px data-[orientation=horizontal]:w-full data-[orientation=vertical]:h-full data-[orientation=vertical]:w-px",
				className,
			)}
			{...props}
		/>
	);
}

export { Separator };
