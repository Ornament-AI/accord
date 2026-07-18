import { CalendarIcon, ChevronLeft, ChevronRight } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { toolbarOutlineClassName } from "@/components/ui/button-variants";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { hasTailwindWidthClass } from "@/lib/tailwind-width-class";
import { cn } from "@/lib/utils";

// --- Types ---

interface YearMonth {
	year: number;
	month: number; // 1-12
}

interface MonthPickerProps {
	/** Current value in "YYYY-MM" format */
	value: string;
	/** Callback when a month is selected */
	onChange: (month: string) => void;
	/** Placeholder text when no value */
	placeholder?: string;
	/** Disabled state */
	disabled?: boolean;
	/**
	 * Optional allow-list of `YYYY-MM` months.
	 * - `undefined`: unconstrained (backward compatible)
	 * - `[]`: no months available (all disabled; year nav bounded to empty)
	 * - non-empty: disable months not in the list; bound year prev/next to available years
	 */
	availableMonths?: string[];
	/** Trigger button className */
	className?: string;
	/** Trigger button style */
	style?: React.CSSProperties;
	/** Trigger button id (for external labels) */
	id?: string;
	/** Accessible label for the trigger button */
	ariaLabel?: string;
	/** Popover alignment */
	align?: "start" | "center" | "end";
}

// --- Constants ---

const MONTH_NAMES = [
	"Jan",
	"Feb",
	"Mar",
	"Apr",
	"May",
	"Jun",
	"Jul",
	"Aug",
	"Sep",
	"Oct",
	"Nov",
	"Dec",
];
const DEFAULT_DISPLAY_YEAR = new Date().getFullYear();

// --- Helper Functions ---

/** Parse "YYYY-MM" string to YearMonth object. Returns null for invalid input. */
function parseYearMonth(str: string | undefined): YearMonth | null {
	if (!str) return null;
	const [yearStr, monthStr] = str.split("-");
	const year = Number.parseInt(yearStr, 10);
	const month = Number.parseInt(monthStr, 10);
	if (Number.isNaN(year) || Number.isNaN(month) || month < 1 || month > 12) return null;
	return { year, month };
}

/** Format YearMonth to "YYYY-MM" string */
function formatYearMonth(ym: YearMonth): string {
	return `${ym.year}-${String(ym.month).padStart(2, "0")}`;
}

/** Check if two YearMonth values are equal */
function equalYearMonth(a: YearMonth | null, b: YearMonth | null): boolean {
	if (!a || !b) return false;
	return a.year === b.year && a.month === b.month;
}

/** Format for display: "Jan 2026" */
function formatMonthDisplay(ym: YearMonth): string {
	return `${MONTH_NAMES[ym.month - 1]} ${ym.year}`;
}

function availableYearBounds(availableMonths: string[] | undefined): {
	constrained: boolean;
	years: number[];
	minYear: number | null;
	maxYear: number | null;
	monthSet: Set<string> | null;
} {
	if (availableMonths === undefined) {
		return { constrained: false, years: [], minYear: null, maxYear: null, monthSet: null };
	}
	const monthSet = new Set(
		availableMonths
			.map((value) => value.slice(0, 7))
			.filter((value) => /^\d{4}-\d{2}$/.test(value)),
	);
	const years = Array.from(
		new Set(Array.from(monthSet).map((value) => Number.parseInt(value.slice(0, 4), 10))),
	)
		.filter((year) => Number.isInteger(year))
		.sort((a, b) => a - b);
	return {
		constrained: true,
		years,
		minYear: years[0] ?? null,
		maxYear: years[years.length - 1] ?? null,
		monthSet,
	};
}

function clampYearToAvailable(
	year: number,
	bounds: ReturnType<typeof availableYearBounds>,
): number {
	if (!bounds.constrained) return year;
	if (bounds.minYear == null || bounds.maxYear == null) return year;
	if (year < bounds.minYear) return bounds.minYear;
	if (year > bounds.maxYear) return bounds.maxYear;
	return year;
}

// --- Component ---

function MonthPicker({
	value,
	onChange,
	placeholder = "Select month",
	disabled = false,
	availableMonths,
	className,
	style,
	id,
	ariaLabel,
	align = "start",
}: MonthPickerProps) {
	const selected = parseYearMonth(value);
	const bounds = React.useMemo(() => availableYearBounds(availableMonths), [availableMonths]);
	const committedDisplayYear = clampYearToAvailable(
		selected?.year ?? bounds.maxYear ?? DEFAULT_DISPLAY_YEAR,
		bounds,
	);
	const [pickerState, setPickerState] = React.useState({
		open: false,
		viewYear: committedDisplayYear,
	});
	const displayYear = pickerState.open
		? clampYearToAvailable(pickerState.viewYear, bounds)
		: committedDisplayYear;

	const canGoPrevYear =
		!bounds.constrained || (bounds.minYear != null && displayYear > bounds.minYear);
	const canGoNextYear =
		!bounds.constrained || (bounds.maxYear != null && displayYear < bounds.maxYear);

	function handleMonthClick(month: number) {
		const clicked: YearMonth = { year: displayYear, month };
		const key = formatYearMonth(clicked);
		if (bounds.monthSet && !bounds.monthSet.has(key)) return;
		onChange(key);
		setPickerState({ open: false, viewYear: clicked.year });
	}

	const displayText = selected ? formatMonthDisplay(selected) : null;

	return (
		<Popover
			open={pickerState.open}
			onOpenChange={(nextOpen) =>
				setPickerState((current) => ({
					open: nextOpen,
					viewYear: nextOpen ? displayYear : current.viewYear,
				}))
			}
		>
			<PopoverTrigger
				render={
					<Button
						data-slot="month-picker-trigger"
						variant="outline"
						disabled={disabled}
						id={id}
						aria-label={ariaLabel}
						style={style}
						className={cn(
							"h-9 min-w-0 justify-start px-3 text-left font-normal",
							toolbarOutlineClassName,
							!hasTailwindWidthClass(className) && "w-[160px]",
							!selected && "text-muted-foreground hover:text-muted-foreground",
							className,
						)}
					/>
				}
			>
				<CalendarIcon size={16} className="mr-2 shrink-0" />
				<span className="min-w-0 truncate">{displayText ?? placeholder}</span>
			</PopoverTrigger>
			<PopoverContent data-slot="month-picker-content" className="w-auto p-3" align={align}>
				{/* Year Navigation */}
				<div className="flex items-center justify-between mb-3">
					<Button
						variant="ghost"
						size="icon-sm"
						disabled={!canGoPrevYear}
						onClick={() =>
							setPickerState((current) => ({
								...current,
								viewYear: clampYearToAvailable(displayYear - 1, bounds),
							}))
						}
						aria-label="Previous year"
					>
						<ChevronLeft size={16} />
					</Button>
					<span className="text-sm font-medium select-none">{displayYear}</span>
					<Button
						variant="ghost"
						size="icon-sm"
						disabled={!canGoNextYear}
						onClick={() =>
							setPickerState((current) => ({
								...current,
								viewYear: clampYearToAvailable(displayYear + 1, bounds),
							}))
						}
						aria-label="Next year"
					>
						<ChevronRight size={16} />
					</Button>
				</div>

				{/* Month Grid */}
				<div className="grid grid-cols-4 gap-1">
					{MONTH_NAMES.map((name, index) => {
						const month = index + 1;
						const current: YearMonth = { year: displayYear, month };
						const key = formatYearMonth(current);
						const isSelected = equalYearMonth(current, selected);
						const isUnavailable = Boolean(bounds.monthSet && !bounds.monthSet.has(key));

						return (
							<button
								key={month}
								type="button"
								disabled={isUnavailable}
								onClick={() => handleMonthClick(month)}
								aria-label={`${name} ${displayYear}`}
								className={cn(
									"h-9 px-2 text-sm font-medium rounded-md transition-colors",
									"hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35",
									"disabled:pointer-events-none disabled:opacity-40",
									isSelected && "bg-primary text-primary-foreground hover:bg-primary/90",
								)}
							>
								{name}
							</button>
						);
					})}
				</div>
			</PopoverContent>
		</Popover>
	);
}

export { MonthPicker, type MonthPickerProps };
