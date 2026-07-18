import type * as React from "react";

import { cn } from "@/lib/utils";

interface TableProps extends React.ComponentProps<"table"> {
	containerClassName?: string;
	surface?: boolean;
}

const tableToneClasses = {
	header: "bg-muted/50",
	headerColumn: "bg-muted/20",
	pinnedHeader: "app-table-pinned-header",
	pinnedColumn: "app-table-pinned-column",
	sectionRow: "bg-muted/20",
	footerRow: "bg-muted/10",
} as const;

function Table({ className, containerClassName, surface = true, ...props }: TableProps) {
	const table = (
		<div
			data-slot="table-container"
			className={cn(
				"app-table-scroll scroll-fade-x relative w-full overflow-x-auto",
				!surface && containerClassName,
			)}
		>
			<table
				data-slot="table"
				className={cn(
					"w-full min-w-full caption-bottom text-sm text-foreground [&_td]:font-normal [&_th]:font-normal",
					className,
				)}
				{...props}
			/>
		</div>
	);

	if (!surface) return table;

	return (
		<div className={cn("app-table-surface overflow-hidden rounded-lg", containerClassName)}>
			{table}
		</div>
	);
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
	return (
		<thead
			data-slot="table-header"
			className={cn("bg-muted/50 border-b border-border", className)}
			{...props}
		/>
	);
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
	return (
		<tbody
			data-slot="table-body"
			className={cn("[&_tr:last-child]:border-0", className)}
			{...props}
		/>
	);
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
	return (
		<tfoot
			data-slot="table-footer"
			className={cn(
				"bg-muted/10 border-t border-border text-sm text-foreground [&>tr]:last:border-b-0",
				className,
			)}
			{...props}
		/>
	);
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
	return (
		<tr
			data-slot="table-row"
			className={cn(
				"border-b border-border hover:bg-muted/10 data-[state=selected]:bg-muted/30 transition-colors min-h-10",
				className,
			)}
			{...props}
		/>
	);
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
	return (
		<th
			data-slot="table-head"
			className={cn(
				"h-11 whitespace-nowrap px-3 text-left align-middle text-xs font-normal text-muted-foreground [&:has([role=checkbox])]:pr-0",
				className,
			)}
			{...props}
		/>
	);
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
	return (
		<td
			data-slot="table-cell"
			className={cn(
				"h-11 whitespace-nowrap px-3 align-middle text-sm text-foreground [&:has([role=checkbox])]:pr-0",
				className,
			)}
			{...props}
		/>
	);
}

function TableCaption({ className, ...props }: React.ComponentProps<"caption">) {
	return (
		<caption
			data-slot="table-caption"
			className={cn("text-muted-foreground mt-4 text-xs", className)}
			{...props}
		/>
	);
}

export {
	Table,
	TableBody,
	TableCaption,
	TableCell,
	TableFooter,
	TableHead,
	TableHeader,
	TableRow,
	tableToneClasses,
};
