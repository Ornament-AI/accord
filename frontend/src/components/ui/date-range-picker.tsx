import { CalendarBlankIcon as CalendarIcon } from "@phosphor-icons/react/dist/csr/CalendarBlank";
import * as React from "react";
import type { DateRange } from "react-day-picker";

import { Button } from "@/components/ui/button";
import { toolbarOutlineClassName } from "@/components/ui/button-variants";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { hasTailwindWidthClass } from "@/lib/tailwind-width-class";
import { cn } from "@/lib/utils";

interface DateRangePreset {
	/** Display label for the preset */
	label: string;
	/** Date range value when preset is selected */
	value: DateRange;
}

interface DateRangePickerProps {
	/** Selected date range */
	value?: DateRange;
	/** Callback when range changes */
	onValueChange?: (range: DateRange | undefined) => void;
	/** Placeholder text when no range selected */
	placeholder?: string;
	/** Date format function for display */
	formatDate?: (date: Date) => string;
	/** Number of months to display side by side */
	numberOfMonths?: 1 | 2;
	/** Disabled state */
	disabled?: boolean;
	/** Accessible label for icon/placeholder-only trigger contexts */
	"aria-label"?: string;
	/** Calendar props passthrough (excludes mode, selected, onSelect, numberOfMonths) */
	calendarProps?: Omit<
		React.ComponentProps<typeof Calendar>,
		"mode" | "selected" | "onSelect" | "numberOfMonths"
	>;
	/** Trigger button className */
	className?: string;
	/** Trigger button style */
	style?: React.CSSProperties;
	/** Popover alignment */
	align?: "start" | "center" | "end";
	/** Optional presets for quick selection */
	presets?: DateRangePreset[];
}

function formatCompactDate(date: Date): string {
	const day = String(date.getDate()).padStart(2, "0");
	const month = String(date.getMonth() + 1).padStart(2, "0");
	const year = String(date.getFullYear()).slice(-2);
	return `${day}/${month}/${year}`;
}

/**
 * DateRangePicker component for selecting a date range.
 *
 * Composes Popover + Calendar (range mode) following shadcn/ui patterns adapted for Base UI.
 *
 * @example
 * ```tsx
 * const [range, setRange] = useState<DateRange>()
 *
 * <DateRangePicker
 *   value={range}
 *   onValueChange={setRange}
 *   numberOfMonths={2}
 *   placeholder="Dates"
 * />
 * ```
 *
 * @example With presets
 * ```tsx
 * const presets: DateRangePreset[] = [
 *   { label: "Last 7 Days", value: { from: subDays(new Date(), 7), to: new Date() } },
 *   { label: "Last 30 Days", value: { from: subDays(new Date(), 30), to: new Date() } },
 * ]
 *
 * <DateRangePicker
 *   value={range}
 *   onValueChange={setRange}
 *   presets={presets}
 * />
 * ```
 */
function DateRangePicker({
	value,
	onValueChange,
	placeholder = "Dates",
	formatDate: formatDateProp = formatCompactDate,
	numberOfMonths = 2,
	disabled = false,
	"aria-label": ariaLabel,
	calendarProps,
	className,
	style,
	align = "start",
	presets,
}: DateRangePickerProps) {
	const [open, setOpen] = React.useState(false);

	// Format the display text based on selected range
	const displayText = React.useMemo(() => {
		if (!value?.from) {
			return value?.to ? `Until ${formatDateProp(value.to)}` : null;
		}

		if (value.to) {
			return `${formatDateProp(value.from)} - ${formatDateProp(value.to)}`;
		}

		return formatDateProp(value.from);
	}, [value, formatDateProp]);

	return (
		<Popover open={open} onOpenChange={setOpen}>
			<PopoverTrigger
				render={
					<Button
						data-slot="date-range-picker-trigger"
						variant="outline"
						disabled={disabled}
						aria-label={ariaLabel}
						style={style}
						className={cn(
							"h-9 min-w-0 justify-start text-left font-normal",
							toolbarOutlineClassName,
							!hasTailwindWidthClass(className) && "w-[280px]",
							!value?.from && "text-muted-foreground hover:text-muted-foreground",
							className,
						)}
					/>
				}
			>
				<CalendarIcon size={16} className="mr-2 shrink-0 text-muted-foreground" />
				<span className="min-w-0 truncate">{displayText ?? placeholder}</span>
			</PopoverTrigger>
			<PopoverContent
				data-slot="date-range-picker-content"
				className={cn("w-auto p-0", presets && presets.length > 0 && "flex")}
				align={align}
			>
				{presets && presets.length > 0 && (
					<div className="flex flex-col gap-1 border-r p-2">
						{presets.map((preset) => (
							<Button
								key={preset.label}
								variant="ghost"
								size="sm"
								className="justify-start text-sm"
								onClick={() => {
									onValueChange?.(preset.value);
									setOpen(false);
								}}
							>
								{preset.label}
							</Button>
						))}
					</div>
				)}
				<Calendar
					mode="range"
					selected={value}
					onSelect={onValueChange}
					numberOfMonths={numberOfMonths}
					defaultMonth={value?.from}
					{...calendarProps}
				/>
			</PopoverContent>
		</Popover>
	);
}

export { DateRangePicker, type DateRangePickerProps, type DateRangePreset };
