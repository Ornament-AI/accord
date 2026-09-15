import { Collapsible as CollapsiblePrimitive } from "@base-ui/react/collapsible";
import { type ComponentProps, useState } from "react";

import { cn } from "@/lib/utils";

function Collapsible({
	open,
	defaultOpen,
	onOpenChange,
	...props
}: ComponentProps<typeof CollapsiblePrimitive.Root>) {
	// `open` is undefined in uncontrolled usage, so mirror the state Base UI
	// reports through onOpenChange — data-state must reflect the real state.
	const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen ?? false);
	const isOpen = open ?? uncontrolledOpen;

	return (
		<CollapsiblePrimitive.Root
			data-slot="collapsible"
			data-state={isOpen ? "open" : "closed"}
			open={open}
			defaultOpen={defaultOpen}
			onOpenChange={(nextOpen, eventDetails) => {
				setUncontrolledOpen(nextOpen);
				onOpenChange?.(nextOpen, eventDetails);
			}}
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
