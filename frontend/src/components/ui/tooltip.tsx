import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip";
import type * as React from "react";

import { cn } from "@/lib/utils";

function TooltipProvider({
	delay = 0,
	delayDuration,
	closeDelay = 0,
	...props
}: React.ComponentProps<typeof TooltipPrimitive.Provider> & {
	delayDuration?: number;
}) {
	return (
		<TooltipPrimitive.Provider
			data-slot="tooltip-provider"
			delay={delayDuration ?? delay}
			closeDelay={closeDelay}
			{...props}
		/>
	);
}

function Tooltip({
	delay,
	delayDuration,
	closeDelay,
	...props
}: React.ComponentProps<typeof TooltipPrimitive.Root> & {
	delay?: number;
	delayDuration?: number;
	closeDelay?: number;
}) {
	return (
		<TooltipProvider delay={delay} delayDuration={delayDuration} closeDelay={closeDelay}>
			<TooltipPrimitive.Root data-slot="tooltip" {...props} />
		</TooltipProvider>
	);
}

function TooltipTrigger({
	render,
	...props
}: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
	return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" render={render} {...props} />;
}

function TooltipContent({
	className,
	sideOffset = 6,
	side = "top",
	align = "center",
	children,
	...props
}: React.ComponentProps<typeof TooltipPrimitive.Popup> & {
	sideOffset?: number;
	side?: "top" | "bottom" | "left" | "right";
	align?: "start" | "center" | "end";
}) {
	return (
		<TooltipPrimitive.Portal>
			<TooltipPrimitive.Positioner
				side={side}
				sideOffset={sideOffset}
				align={align}
				data-slot="tooltip-positioner"
				className="pointer-events-none isolate z-50"
			>
				<TooltipPrimitive.Popup
					data-slot="tooltip-content"
					className={cn(
						"accord-motion-tooltip pointer-events-none select-none relative bg-foreground text-background z-50 max-w-xs w-fit origin-(--transform-origin) rounded-md px-3 py-1.5 text-xs leading-snug text-pretty",
						className,
					)}
					{...props}
				>
					{children}
					<TooltipPrimitive.Arrow className="flex text-foreground data-[side=bottom]:-top-2 data-[side=bottom]:rotate-0 data-[side=left]:right-[-9px] data-[side=left]:rotate-90 data-[side=right]:left-[-9px] data-[side=right]:-rotate-90 data-[side=top]:-bottom-2 data-[side=top]:rotate-180">
						<TooltipArrowSvg className="fill-current" />
					</TooltipPrimitive.Arrow>
				</TooltipPrimitive.Popup>
			</TooltipPrimitive.Positioner>
		</TooltipPrimitive.Portal>
	);
}

function TooltipArrowSvg(props: React.ComponentProps<"svg">) {
	return (
		<svg width="20" height="10" viewBox="0 0 20 10" fill="none" {...props}>
			<title>Tooltip arrow</title>
			<path d="M0 10L10 0L20 10H0Z" />
		</svg>
	);
}

export { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger };
