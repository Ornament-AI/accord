import type { ReactNode } from "react";

import { DataEntryFieldError } from "@/components/data-entry/DataEntryFieldError";
import { DataEntryFieldLabel } from "@/components/data-entry/DataEntryFieldLabel";
import { cn } from "@/lib/utils";

/**
 * A single data-entry field: a label row stacked over a control (+ optional
 * error) row.
 *
 * Layout contract: the field is a two-row CSS subgrid that spans two rows of
 * its parent grid. When several fields live in the same {@link DataEntryFieldGrid}
 * they share the same two row tracks, so every control lines up horizontally
 * even when one label wraps to two lines.
 */
type DataEntryFieldProps = {
	label?: ReactNode;
	htmlFor?: string;
	labelId?: string;
	/** Rendered in the label row, either beside the label or at the trailing edge. */
	labelAccessory?: ReactNode;
	labelAccessoryPlacement?: "inline" | "end";
	required?: boolean;
	error?: string;
	errorId?: string;
	children: ReactNode;
	className?: string;
};

export function DataEntryField({
	label,
	htmlFor,
	labelId,
	labelAccessory,
	labelAccessoryPlacement = "end",
	required,
	error,
	errorId,
	children,
	className,
}: DataEntryFieldProps) {
	const inlineAccessory = labelAccessoryPlacement === "inline" ? labelAccessory : null;
	const endAccessory = labelAccessoryPlacement === "end" ? labelAccessory : null;

	return (
		<div className={cn("row-span-2 grid grid-rows-subgrid gap-y-2", className)}>
			<div className="flex min-w-0 items-end justify-between gap-2 self-end">
				<div className="flex min-w-0 items-center gap-1.5">
					{label != null ? (
						<DataEntryFieldLabel htmlFor={htmlFor} id={labelId} required={required}>
							{label}
						</DataEntryFieldLabel>
					) : (
						<span aria-hidden className="sr-only" />
					)}
					{inlineAccessory ? <div className="shrink-0">{inlineAccessory}</div> : null}
				</div>
				{endAccessory ? <div className="shrink-0">{endAccessory}</div> : null}
			</div>
			<div className="flex min-w-0 flex-col gap-1.5">
				<div className="min-w-0">{children}</div>
				<DataEntryFieldError id={errorId}>{error}</DataEntryFieldError>
			</div>
		</div>
	);
}
