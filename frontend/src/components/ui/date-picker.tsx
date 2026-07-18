import { CalendarIcon } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { toolbarOutlineClassName } from "@/components/ui/button-variants";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn, formatDate } from "@/lib/utils";

interface DatePickerProps {
	/** Trigger id for label association */
	id?: string;
	/** Selected date value */
	value?: Date;
	/** Callback when date changes */
	onValueChange?: (date: Date | undefined) => void;
	/** Placeholder text when no date selected */
	placeholder?: string;
	/** Date format function for display */
	formatDate?: (date: Date) => string;
	/** Disabled state */
	disabled?: boolean;
	/** Error state */
	"aria-invalid"?: "true" | undefined;
	/** Error/help text id */
	"aria-describedby"?: string;
	/** Accessible label for icon/placeholder-only trigger contexts */
	"aria-label"?: string;
	/** Calendar props passthrough (excludes mode, selected, onSelect) */
	calendarProps?: Omit<React.ComponentProps<typeof Calendar>, "mode" | "selected" | "onSelect">;
	/** Trigger button className */
	className?: string;
	/** Popover alignment */
	align?: "start" | "center" | "end";
}

/**
 * DatePicker component for single date selection.
 *
 * Composes Popover + Calendar following shadcn/ui patterns adapted for Base UI.
 *
 * @example
 * ```tsx
 * const [date, setDate] = useState<Date>()
 *
 * <DatePicker
 *   value={date}
 *   onValueChange={setDate}
 *   placeholder="Date"
 * />
 * ```
 */
function DatePicker({
	id,
	value,
	onValueChange,
	placeholder = "Date",
	formatDate: formatDateProp = formatDate,
	disabled = false,
	"aria-invalid": ariaInvalid,
	"aria-describedby": ariaDescribedBy,
	"aria-label": ariaLabel,
	calendarProps,
	className,
	align = "start",
}: DatePickerProps) {
	const [open, setOpen] = React.useState(false);

	return (
		<Popover open={open} onOpenChange={setOpen}>
			<PopoverTrigger
				render={
					<Button
						data-slot="date-picker-trigger"
						type="button"
						id={id}
						variant="outline"
						disabled={disabled}
						aria-label={ariaLabel}
						aria-invalid={ariaInvalid}
						aria-describedby={ariaDescribedBy}
						className={cn(
							"h-9 w-auto min-w-0 justify-start text-left font-normal",
							toolbarOutlineClassName,
							!value && "text-muted-foreground hover:text-muted-foreground",
							className,
						)}
					/>
				}
			>
				<CalendarIcon size={16} className="mr-2 shrink-0 text-muted-foreground" />
				{value ? (
					<span className="min-w-0 truncate tabular-nums">{formatDateProp(value)}</span>
				) : (
					<span className="min-w-0 truncate">{placeholder}</span>
				)}
			</PopoverTrigger>
			<PopoverContent data-slot="date-picker-content" className="w-auto p-0" align={align}>
				<Calendar
					mode="single"
					selected={value}
					onSelect={(date) => {
						onValueChange?.(date);
						setOpen(false);
					}}
					defaultMonth={value}
					{...calendarProps}
				/>
			</PopoverContent>
		</Popover>
	);
}

export { DatePicker, type DatePickerProps };
