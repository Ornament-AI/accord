import { useRender } from "@base-ui/react/use-render";
import type { VariantProps } from "class-variance-authority";
import type * as React from "react";

import { badgeVariants } from "@/components/ui/badge-variants";
import { cn } from "@/lib/utils";

interface BadgeProps
	extends React.HTMLAttributes<HTMLSpanElement>,
		VariantProps<typeof badgeVariants> {
	render?:
		| React.ReactElement
		| ((props: React.HTMLAttributes<HTMLSpanElement>) => React.ReactElement);
}

function Badge({ className, variant, render, ...props }: BadgeProps) {
	const mergedProps = {
		"data-slot": "badge",
		className: cn(badgeVariants({ variant }), className),
		...props,
	};

	return useRender({
		render: render ?? <span />,
		props: mergedProps,
	});
}

export { Badge };
