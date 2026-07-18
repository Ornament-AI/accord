import { Tabs as TabsPrimitive } from "@base-ui/react/tabs";
import type { VariantProps } from "class-variance-authority";
import type * as React from "react";

import { tabsListVariants } from "@/components/ui/tabs-variants";
import { cn } from "@/lib/utils";

/**
 * Tabs component built on Base UI.
 *
 * @example
 * ```tsx
 * <Tabs defaultValue="account">
 *   <TabsList>
 *     <TabsTrigger value="account">Account</TabsTrigger>
 *     <TabsTrigger value="password">Password</TabsTrigger>
 *   </TabsList>
 *   <TabsContent value="account">Account settings here</TabsContent>
 *   <TabsContent value="password">Password settings here</TabsContent>
 * </Tabs>
 * ```
 */
function Tabs({
	className,
	orientation = "horizontal",
	...props
}: React.ComponentProps<typeof TabsPrimitive.Root>) {
	return (
		<TabsPrimitive.Root
			data-slot="tabs"
			data-orientation={orientation}
			orientation={orientation}
			className={cn("group/tabs flex gap-2 data-[orientation=horizontal]:flex-col", className)}
			{...props}
		/>
	);
}

function TabsList({
	className,
	variant = "default",
	children,
	...props
}: React.ComponentProps<typeof TabsPrimitive.List> & VariantProps<typeof tabsListVariants>) {
	return (
		<TabsPrimitive.List
			data-slot="tabs-list"
			data-variant={variant}
			className={cn(
				"accord-motion-tabs-list relative isolate",
				tabsListVariants({ variant }),
				className,
			)}
			{...props}
		>
			<TabsPrimitive.Indicator
				data-slot="tabs-indicator"
				className="accord-motion-tabs-indicator"
			/>
			{children}
		</TabsPrimitive.List>
	);
}

/**
 * Individual tab trigger. Uses Base UI's Tabs.Tab internally.
 * Named TabsTrigger for API compatibility with existing code.
 */
function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Tab>) {
	return (
		<TabsPrimitive.Tab
			data-slot="tabs-trigger"
			className={cn(
				"accord-motion-tabs-trigger focus-visible:ring-ring/50 text-foreground/60 hover:text-foreground dark:text-muted-foreground dark:hover:text-foreground relative z-10 inline-flex h-[calc(100%-1px)] flex-1 items-center justify-center gap-1.5 rounded-md border border-transparent px-2 py-1 text-sm font-medium whitespace-nowrap group-data-[orientation=vertical]/tabs:w-full group-data-[orientation=vertical]/tabs:justify-start focus-visible:bg-muted/55 focus-visible:ring-1 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 group-data-[variant=default]/tabs-list:data-active:shadow-none group-data-[variant=line]/tabs-list:data-active:shadow-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
				"group-data-[variant=line]/tabs-list:bg-transparent group-data-[variant=line]/tabs-list:data-active:bg-transparent dark:group-data-[variant=line]/tabs-list:data-active:border-transparent dark:group-data-[variant=line]/tabs-list:data-active:bg-transparent",
				"group-data-[variant=line]/tabs-list:focus-visible:bg-transparent",
				"data-active:text-primary dark:data-active:text-primary",
				className,
			)}
			{...props}
		/>
	);
}

/**
 * Tab panel content. Uses Base UI's Tabs.Panel internally.
 * Named TabsContent for API compatibility with existing code.
 */
function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Panel>) {
	return (
		<TabsPrimitive.Panel
			data-slot="tabs-content"
			className={cn("flex-1 outline-none", className)}
			{...props}
		/>
	);
}

export { Tabs, TabsContent, TabsList, TabsTrigger };
