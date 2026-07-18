import { Popover as PopoverPrimitive } from "@base-ui/react/popover";

import { cn } from "@/lib/utils";

/**
 * Popover component built on Base UI.
 *
 * @example
 * ```tsx
 * <Popover>
 *   <PopoverTrigger>Open</PopoverTrigger>
 *   <PopoverContent>Content here</PopoverContent>
 * </Popover>
 * ```
 */
function Popover({ ...props }: PopoverPrimitive.Root.Props) {
	return <PopoverPrimitive.Root data-slot="popover" {...props} />;
}

function PopoverTrigger({ ...props }: PopoverPrimitive.Trigger.Props) {
	return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />;
}

/**
 * Popover content with positioning props.
 *
 * Note: Base UI uses the Positioner's `anchor` prop instead of a separate
 * Anchor component. To anchor the popover to an element other than the trigger:
 *
 * @example
 * ```tsx
 * const anchorRef = React.useRef(null)
 *
 * <div ref={anchorRef}>Anchor element</div>
 * <Popover>
 *   <PopoverTrigger>Open</PopoverTrigger>
 *   <PopoverContent anchor={anchorRef}>
 *     Content anchored to the div above
 *   </PopoverContent>
 * </Popover>
 * ```
 */
function PopoverContent({
	className,
	align = "center",
	side = "bottom",
	sideOffset = 10,
	anchor,
	...props
}: PopoverPrimitive.Popup.Props &
	Pick<PopoverPrimitive.Positioner.Props, "align" | "side" | "sideOffset" | "anchor">) {
	return (
		<PopoverPrimitive.Portal>
			<PopoverPrimitive.Positioner
				data-slot="popover-positioner"
				align={align}
				side={side}
				sideOffset={sideOffset}
				anchor={anchor}
				className="isolate z-50"
			>
				<PopoverPrimitive.Popup
					data-slot="popover-content"
					className={cn(
						"accord-motion-popover bg-popover/98 text-popover-foreground app-material-overlay w-72 origin-(--transform-origin) overflow-hidden rounded-md backdrop-blur-[1.5px] p-4 outline-hidden",
						className,
					)}
					{...props}
				/>
			</PopoverPrimitive.Positioner>
		</PopoverPrimitive.Portal>
	);
}

function PopoverHeader({ className, ...props }: React.ComponentProps<"div">) {
	return (
		<div
			data-slot="popover-header"
			className={cn("flex flex-col gap-1 text-sm", className)}
			{...props}
		/>
	);
}

function PopoverTitle({ className, ...props }: PopoverPrimitive.Title.Props) {
	return (
		<PopoverPrimitive.Title
			data-slot="popover-title"
			className={cn("font-medium", className)}
			{...props}
		/>
	);
}

function PopoverDescription({ className, ...props }: PopoverPrimitive.Description.Props) {
	return (
		<PopoverPrimitive.Description
			data-slot="popover-description"
			className={cn("text-muted-foreground", className)}
			{...props}
		/>
	);
}

export { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger };
