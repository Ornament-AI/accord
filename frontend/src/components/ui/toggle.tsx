import { Toggle as TogglePrimitive } from "@base-ui/react/toggle";
import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

const toggleVariants = cva(
	"inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium outline-none transition-[color,background-color,border-color,box-shadow] hover:bg-muted hover:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/35 disabled:pointer-events-none disabled:opacity-50 data-[pressed]:bg-accent data-[pressed]:text-accent-foreground [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
	{
		variants: {
			variant: {
				default: "bg-transparent",
				outline:
					"border border-border bg-background/86 shadow-xs hover:bg-accent/62 hover:text-foreground dark:bg-input/44 dark:hover:bg-input/62 data-[pressed]:bg-accent data-[pressed]:shadow-sm",
			},
			size: {
				default: "h-9 min-w-9 px-3",
				sm: "h-8 min-w-8 px-2",
				lg: "h-10 min-w-10 px-3",
			},
		},
		defaultVariants: {
			variant: "default",
			size: "default",
		},
	},
);

function Toggle({
	className,
	variant = "default",
	size = "default",
	...props
}: React.ComponentProps<typeof TogglePrimitive> & VariantProps<typeof toggleVariants>) {
	return (
		<TogglePrimitive
			data-slot="toggle"
			data-variant={variant}
			data-size={size}
			className={cn(toggleVariants({ variant, size, className }))}
			{...props}
		/>
	);
}

export { Toggle, toggleVariants };
