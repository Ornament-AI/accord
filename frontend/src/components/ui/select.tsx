import { Select as SelectPrimitive } from "@base-ui/react/select";
import { CheckIcon, ChevronDownIcon, ChevronUpIcon } from "lucide-react";
import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Select wrapper maintaining Radix-like onValueChange signature.
 * Base UI: onValueChange(value: unknown, eventDetails)
 * This wrapper: onValueChange(value: string)
 *
 * @example
 * ```tsx
 * <Select items={items} onValueChange={(value) => console.log(value)}>
 *   <SelectTrigger>
 *     <SelectValue placeholder="Select..." />
 *   </SelectTrigger>
 *   <SelectContent>
 *     <SelectGroup>
 *       <SelectItem value="a">Option A</SelectItem>
 *       <SelectItem value="b">Option B</SelectItem>
 *     </SelectGroup>
 *   </SelectContent>
 * </Select>
 * ```
 */
function Select({
	onValueChange,
	...props
}: Omit<React.ComponentProps<typeof SelectPrimitive.Root>, "onValueChange"> & {
	/** Callback fired when the value changes. Receives the selected value as a string. */
	onValueChange?: (value: string) => void;
}) {
	return (
		<SelectPrimitive.Root
			data-slot="select"
			onValueChange={onValueChange ? (value) => onValueChange(value as string) : undefined}
			{...props}
		/>
	);
}

function SelectGroup({ ...props }: React.ComponentProps<typeof SelectPrimitive.Group>) {
	return <SelectPrimitive.Group data-slot="select-group" {...props} />;
}

function SelectValue({ ...props }: React.ComponentProps<typeof SelectPrimitive.Value>) {
	return <SelectPrimitive.Value data-slot="select-value" {...props} />;
}

function SelectTrigger({
	className,
	size = "default",
	children,
	...props
}: React.ComponentProps<typeof SelectPrimitive.Trigger> & {
	size?: "sm" | "default";
}) {
	return (
		<SelectPrimitive.Trigger
			data-slot="select-trigger"
			data-size={size}
			className={cn(
				"border-border data-[placeholder]:text-muted-foreground [&_svg:not([class*='text-'])]:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/35 aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive dark:bg-input/22 dark:border-border dark:hover:bg-input/38 dark:hover:border-border flex w-fit items-center justify-between gap-2 rounded-md border bg-transparent px-3 py-1 text-base whitespace-nowrap shadow-2xs dark:shadow-xs transition-[color,box-shadow,border-color,background-color] outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-50 data-[size=default]:h-9 data-[size=sm]:h-8 md:text-sm *:data-[slot=select-value]:line-clamp-1 *:data-[slot=select-value]:flex *:data-[slot=select-value]:items-center *:data-[slot=select-value]:gap-2 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
				className,
			)}
			{...props}
		>
			{children}
			<SelectPrimitive.Icon data-slot="select-icon">
				<ChevronDownIcon className="size-4 opacity-50" />
			</SelectPrimitive.Icon>
		</SelectPrimitive.Trigger>
	);
}

function SelectContent({
	className,
	children,
	position = "item-aligned",
	side = "bottom",
	align = "center",
	sideOffset = 10,
	...props
}: React.ComponentProps<typeof SelectPrimitive.Popup> & {
	position?: "item-aligned" | "popper";
	side?: "bottom" | "top";
	align?: "start" | "center" | "end";
	sideOffset?: number;
}) {
	return (
		<SelectPrimitive.Portal>
			<SelectPrimitive.Positioner
				data-slot="select-positioner"
				side={side}
				sideOffset={sideOffset}
				align={align}
				className="isolate z-50 outline-none"
			>
				<SelectPrimitive.Popup
					data-slot="select-content"
					data-position={position}
					className={cn(
						"accord-motion-popover bg-popover/98 text-popover-foreground app-material-overlay relative w-(--anchor-width) max-w-(--available-width) min-w-[max(8rem,var(--anchor-width))] origin-(--transform-origin) overflow-hidden rounded-md backdrop-blur-[1.5px]",
						position === "popper" &&
							"data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1",
						className,
					)}
					{...props}
				>
					<SelectScrollUpButton />
					<SelectPrimitive.List
						data-slot="select-list"
						className={cn(
							"app-scrollbar max-h-[min(calc(--spacing(96)---spacing(9)),calc(var(--available-height)---spacing(9)))] scroll-fade scroll-py-1 overflow-y-auto p-1",
							position === "popper" &&
								"h-[var(--anchor-height)] w-full min-w-[var(--anchor-width)] scroll-my-1",
						)}
					>
						{children}
					</SelectPrimitive.List>
					<SelectScrollDownButton />
				</SelectPrimitive.Popup>
			</SelectPrimitive.Positioner>
		</SelectPrimitive.Portal>
	);
}

function SelectLabel({
	className,
	...props
}: React.ComponentProps<typeof SelectPrimitive.GroupLabel>) {
	return (
		<SelectPrimitive.GroupLabel
			data-slot="select-label"
			className={cn("text-muted-foreground px-2 py-1.5 text-xs", className)}
			{...props}
		/>
	);
}

function SelectItem({
	className,
	children,
	...props
}: React.ComponentProps<typeof SelectPrimitive.Item>) {
	return (
		<SelectPrimitive.Item
			data-slot="select-item"
			className={cn(
				"data-highlighted:bg-accent data-highlighted:text-accent-foreground [&_svg:not([class*='text-'])]:text-muted-foreground relative flex w-full cursor-default items-center gap-2 rounded-sm py-1.5 pr-8 pl-2 text-sm outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 *:[span]:last:flex *:[span]:last:items-center *:[span]:last:gap-2",
				className,
			)}
			{...props}
		>
			<span
				data-slot="select-item-indicator"
				className="absolute right-2 flex size-3.5 items-center justify-center"
			>
				<SelectPrimitive.ItemIndicator>
					<CheckIcon className="size-4" />
				</SelectPrimitive.ItemIndicator>
			</span>
			<SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
		</SelectPrimitive.Item>
	);
}

function SelectSeparator({
	className,
	...props
}: React.ComponentProps<typeof SelectPrimitive.Separator>) {
	return (
		<SelectPrimitive.Separator
			data-slot="select-separator"
			className={cn("bg-border pointer-events-none -mx-1 my-1 h-px", className)}
			{...props}
		/>
	);
}

function SelectScrollUpButton({
	className,
	...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollUpArrow>) {
	return (
		<SelectPrimitive.ScrollUpArrow
			data-slot="select-scroll-up-button"
			className={cn("flex cursor-default items-center justify-center py-1", className)}
			{...props}
		>
			<ChevronUpIcon className="size-4" />
		</SelectPrimitive.ScrollUpArrow>
	);
}

function SelectScrollDownButton({
	className,
	...props
}: React.ComponentProps<typeof SelectPrimitive.ScrollDownArrow>) {
	return (
		<SelectPrimitive.ScrollDownArrow
			data-slot="select-scroll-down-button"
			className={cn("flex cursor-default items-center justify-center py-1", className)}
			{...props}
		>
			<ChevronDownIcon className="size-4" />
		</SelectPrimitive.ScrollDownArrow>
	);
}

export {
	Select,
	SelectContent,
	SelectGroup,
	SelectItem,
	SelectLabel,
	SelectScrollDownButton,
	SelectScrollUpButton,
	SelectSeparator,
	SelectTrigger,
	SelectValue,
};
