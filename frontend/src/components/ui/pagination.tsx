import { useRender } from "@base-ui/react/use-render";
import type { VariantProps } from "class-variance-authority";
import { ChevronLeftIcon, ChevronRightIcon, MoreHorizontalIcon } from "lucide-react";
import type * as React from "react";

import { buttonVariants } from "@/components/ui/button-variants";
import { cn } from "@/lib/utils";

function Pagination({ className, ...props }: React.ComponentProps<"nav">) {
	return (
		<nav
			aria-label="pagination"
			data-slot="pagination"
			className={cn("mx-auto flex w-full justify-center", className)}
			{...props}
		/>
	);
}

function PaginationContent({ className, ...props }: React.ComponentProps<"ul">) {
	return (
		<ul
			data-slot="pagination-content"
			className={cn("flex flex-row items-center gap-1", className)}
			{...props}
		/>
	);
}

function PaginationItem({ ...props }: React.ComponentProps<"li">) {
	return <li data-slot="pagination-item" {...props} />;
}

type PaginationLinkProps = Omit<useRender.ComponentProps<"a">, "color"> &
	Pick<VariantProps<typeof buttonVariants>, "size"> & {
		isActive?: boolean;
	};

function PaginationLink({
	className,
	isActive,
	size = "icon",
	render,
	...props
}: PaginationLinkProps) {
	return useRender({
		render,
		defaultTagName: "a",
		props: {
			...props,
			"aria-current": isActive ? "page" : props["aria-current"],
			"data-active": isActive ? "" : undefined,
			"data-slot": "pagination-link",
			className: cn(
				buttonVariants({
					variant: isActive ? "outline" : "ghost",
					size,
				}),
				className,
			),
		},
	});
}

function PaginationPrevious({
	className,
	text = "Previous",
	...props
}: PaginationLinkProps & {
	text?: string;
}) {
	return (
		<PaginationLink
			aria-label="Go to Previous Page"
			size="default"
			className={cn("gap-1 px-2.5 sm:pl-2.5", className)}
			{...props}
		>
			<ChevronLeftIcon />
			<span className="hidden sm:block">{text}</span>
		</PaginationLink>
	);
}

function PaginationNext({
	className,
	text = "Next",
	...props
}: PaginationLinkProps & {
	text?: string;
}) {
	return (
		<PaginationLink
			aria-label="Go to Next Page"
			size="default"
			className={cn("gap-1 px-2.5 sm:pr-2.5", className)}
			{...props}
		>
			<span className="hidden sm:block">{text}</span>
			<ChevronRightIcon />
		</PaginationLink>
	);
}

function PaginationEllipsis({ className, ...props }: React.ComponentProps<"span">) {
	return (
		<span
			aria-hidden
			data-slot="pagination-ellipsis"
			className={cn("flex size-9 items-center justify-center", className)}
			{...props}
		>
			<MoreHorizontalIcon className="size-4" />
			<span className="sr-only">More pages</span>
		</span>
	);
}

export {
	Pagination,
	PaginationContent,
	PaginationEllipsis,
	PaginationItem,
	PaginationLink,
	PaginationNext,
	PaginationPrevious,
};
