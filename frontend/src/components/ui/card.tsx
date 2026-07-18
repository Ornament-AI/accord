import { cn } from "@/lib/utils";

function Card({
	className,
	size = "default",
	ref,
	...props
}: React.ComponentProps<"div"> & { size?: "default" | "sm"; ref?: React.Ref<HTMLDivElement> }) {
	return (
		<div
			ref={ref}
			data-slot="card"
			data-size={size}
			className={cn(
				"app-material-level-1 border app-border-level-1 bg-card text-card-foreground gap-6 overflow-hidden rounded-lg py-6 text-sm has-[>img:first-child]:pt-0 data-[size=sm]:gap-4 data-[size=sm]:py-4 *:has(>img:first-child):rounded-t-lg *:has(>img:last-child):rounded-b-lg group/card flex flex-col",
				className,
			)}
			{...props}
		/>
	);
}

function CardHeader({
	className,
	ref,
	...props
}: React.ComponentProps<"div"> & { ref?: React.Ref<HTMLDivElement> }) {
	return (
		<div
			ref={ref}
			data-slot="card-header"
			className={cn(
				"gap-1 rounded-t-lg px-6 group-data-[size=sm]/card:px-4 [&.border-b]:pb-6 group-data-[size=sm]/card:[&.border-b]:pb-4 group/card-header @container/card-header grid auto-rows-min items-start has-data-[slot=card-action]:grid-cols-[1fr_auto] has-data-[slot=card-description]:grid-rows-[auto_auto]",
				className,
			)}
			{...props}
		/>
	);
}

function CardTitle({
	className,
	ref,
	...props
}: React.ComponentProps<"div"> & { ref?: React.Ref<HTMLDivElement> }) {
	return (
		<div
			ref={ref}
			data-slot="card-title"
			className={cn(
				"text-base leading-normal font-medium group-data-[size=sm]/card:text-sm",
				className,
			)}
			{...props}
		/>
	);
}

function CardDescription({
	className,
	ref,
	...props
}: React.ComponentProps<"div"> & { ref?: React.Ref<HTMLDivElement> }) {
	return (
		<div
			ref={ref}
			data-slot="card-description"
			className={cn("text-muted-foreground text-sm", className)}
			{...props}
		/>
	);
}

function CardAction({
	className,
	ref,
	...props
}: React.ComponentProps<"div"> & { ref?: React.Ref<HTMLDivElement> }) {
	return (
		<div
			ref={ref}
			data-slot="card-action"
			className={cn("col-start-2 row-span-2 row-start-1 self-start justify-self-end", className)}
			{...props}
		/>
	);
}

function CardContent({
	className,
	ref,
	...props
}: React.ComponentProps<"div"> & { ref?: React.Ref<HTMLDivElement> }) {
	return (
		<div
			ref={ref}
			data-slot="card-content"
			className={cn("px-6 group-data-[size=sm]/card:px-4", className)}
			{...props}
		/>
	);
}

function CardFooter({
	className,
	ref,
	...props
}: React.ComponentProps<"div"> & { ref?: React.Ref<HTMLDivElement> }) {
	return (
		<div
			ref={ref}
			data-slot="card-footer"
			className={cn(
				"rounded-b-lg px-6 group-data-[size=sm]/card:px-4 [&.border-t]:pt-6 group-data-[size=sm]/card:[&.border-t]:pt-4 flex items-center",
				className,
			)}
			{...props}
		/>
	);
}

export { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle };
