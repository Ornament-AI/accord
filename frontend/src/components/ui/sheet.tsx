import { Dialog as SheetPrimitive } from "@base-ui/react/dialog";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import type * as React from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * Sheet component built on Base UI Dialog.
 *
 * A Sheet is a dialog variant that slides in from the edge of the screen.
 * It uses the same primitives as Dialog but with slide animations.
 *
 * Note: Base UI uses the `render` prop pattern for composition.
 *
 * @example
 * ```tsx
 * <Sheet>
 *   <SheetTrigger render={<Button />}>Open</SheetTrigger>
 *   <SheetContent side="right">
 *     <SheetHeader>
 *       <SheetTitle>Settings</SheetTitle>
 *     </SheetHeader>
 *   </SheetContent>
 * </Sheet>
 * ```
 */
function Sheet({ ...props }: React.ComponentProps<typeof SheetPrimitive.Root>) {
	return <SheetPrimitive.Root data-slot="sheet" {...props} />;
}

/**
 * Trigger that opens the sheet.
 * Use the `render` prop to render as a custom element.
 *
 * @example
 * ```tsx
 * <SheetTrigger render={<Button variant="outline" />}>
 *   Open Menu
 * </SheetTrigger>
 * ```
 */
function SheetTrigger({ render, ...props }: React.ComponentProps<typeof SheetPrimitive.Trigger>) {
	return <SheetPrimitive.Trigger data-slot="sheet-trigger" render={render} {...props} />;
}

function SheetClose({ render, ...props }: React.ComponentProps<typeof SheetPrimitive.Close>) {
	return <SheetPrimitive.Close data-slot="sheet-close" render={render} {...props} />;
}

function SheetPortal({ ...props }: React.ComponentProps<typeof SheetPrimitive.Portal>) {
	return <SheetPrimitive.Portal data-slot="sheet-portal" {...props} />;
}

function SheetOverlay({
	className,
	...props
}: React.ComponentProps<typeof SheetPrimitive.Backdrop>) {
	return (
		<SheetPrimitive.Backdrop
			data-slot="sheet-overlay"
			className={cn(
				"accord-motion-overlay fixed inset-0 z-50 bg-black/62 backdrop-blur-[3px]",
				className,
			)}
			{...props}
		/>
	);
}

function SheetContent({
	className,
	children,
	side = "right",
	showCloseButton = true,
	...props
}: React.ComponentProps<typeof SheetPrimitive.Popup> & {
	side?: "top" | "right" | "bottom" | "left";
	showCloseButton?: boolean;
}) {
	return (
		<SheetPortal>
			<SheetOverlay />
			<SheetPrimitive.Popup
				data-slot="sheet-content"
				data-side={side}
				className={cn(
					"accord-motion-sheet bg-background fixed z-50 flex flex-col gap-4 shadow-lg outline-none",
					side === "right" && "inset-y-0 right-0 h-full w-3/4 border-l sm:max-w-sm",
					side === "left" && "inset-y-0 left-0 h-full w-3/4 border-r sm:max-w-sm",
					side === "top" && "inset-x-0 top-0 h-auto border-b",
					side === "bottom" && "inset-x-0 bottom-0 h-auto border-t",
					className,
				)}
				{...props}
			>
				{children}
				{showCloseButton && (
					<SheetPrimitive.Close
						data-slot="sheet-close"
						render={
							<Button
								variant="ghost"
								size="icon"
								aria-label="Close"
								className="absolute top-3 right-3 bg-transparent text-muted-foreground shadow-none hover:bg-transparent hover:text-foreground hover:shadow-none dark:hover:bg-transparent"
							/>
						}
					>
						<XIcon weight="bold" aria-hidden />
					</SheetPrimitive.Close>
				)}
			</SheetPrimitive.Popup>
		</SheetPortal>
	);
}

function SheetHeader({ className, ...props }: React.ComponentProps<"div">) {
	return (
		<div
			data-slot="sheet-header"
			className={cn("flex flex-col gap-1.5 p-4", className)}
			{...props}
		/>
	);
}

function SheetFooter({ className, ...props }: React.ComponentProps<"div">) {
	return (
		<div
			data-slot="sheet-footer"
			className={cn("mt-auto flex flex-col gap-2 p-4", className)}
			{...props}
		/>
	);
}

function SheetTitle({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Title>) {
	return (
		<SheetPrimitive.Title
			data-slot="sheet-title"
			className={cn("text-foreground font-semibold", className)}
			{...props}
		/>
	);
}

function SheetDescription({
	className,
	...props
}: React.ComponentProps<typeof SheetPrimitive.Description>) {
	return (
		<SheetPrimitive.Description
			data-slot="sheet-description"
			className={cn("text-muted-foreground text-sm", className)}
			{...props}
		/>
	);
}

export {
	Sheet,
	SheetClose,
	SheetContent,
	SheetDescription,
	SheetFooter,
	SheetHeader,
	SheetTitle,
	SheetTrigger,
};
