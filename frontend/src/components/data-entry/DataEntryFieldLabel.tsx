import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type FieldLabelProps = {
	children: ReactNode;
	htmlFor?: string;
	id?: string;
	className?: string;
	required?: boolean;
};

export function DataEntryFieldLabel({
	children,
	htmlFor,
	id,
	className,
	required,
}: FieldLabelProps) {
	const labelClassName = cn(
		"text-sm leading-tight font-medium text-foreground",
		required && "after:ml-0.5 after:text-destructive after:content-['*']",
		className,
	);
	return htmlFor ? (
		<label htmlFor={htmlFor} id={id} className={labelClassName}>
			{children}
		</label>
	) : (
		<span id={id} className={labelClassName}>
			{children}
		</span>
	);
}
