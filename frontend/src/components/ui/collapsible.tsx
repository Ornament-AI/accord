import { Collapsible as CollapsiblePrimitive } from "@base-ui/react/collapsible";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

function Collapsible({ open, ...props }: ComponentProps<typeof CollapsiblePrimitive.Root>) {
	return (
		<CollapsiblePrimitive.Root
			data-slot="collapsible"
			data-state={open ? "open" : "closed"}
			open={open}
			{...props}
		/>
	);
}

function CollapsibleContent({
	className,
	...props
}: ComponentProps<typeof CollapsiblePrimitive.Panel>) {
	return (
		<CollapsiblePrimitive.Panel
			data-slot="collapsible-content"
			className={cn("accord-motion-collapsible", className)}
			{...props}
		/>
	);
}

function CollapsibleTrigger({ ...props }: ComponentProps<typeof CollapsiblePrimitive.Trigger>) {
	return <CollapsiblePrimitive.Trigger data-slot="collapsible-trigger" {...props} />;
}

export { Collapsible, CollapsibleContent, CollapsibleTrigger };
