import type { CSSProperties } from "react";

/**
 * Combobox/Select trigger chrome budget — horizontal padding (px-3 ≈ 1.5ch on
 * each side) plus the chevron icon and its gap. Added to the content width so
 * the visible label is never clipped.
 */
const FILTER_WIDTH_PADDING_CH = 5;

/**
 * Toolbar visual rhythm: filter chips stay between these character widths so a
 * row of mixed filters reads as a consistent grid rather than each chip
 * sizing to its own content. Tuned against the data-page toolbar at laptop
 * widths; callers can override per-filter when a label genuinely needs more.
 */
const DEFAULT_MIN_CH = 12;
const DEFAULT_MAX_CH = 16;
const DATE_RANGE_VALUE_LABEL = "00/00/00 - 00/00/00";

/**
 * Content-fit width for a filter control: sized to the longest of its option
 * labels and placeholder, clamped between `minCh` and `maxCh`, plus padding
 * for the trigger chrome (chevron + side padding).
 */
export function filterWidthStyle(
	labels: readonly string[],
	placeholder: string,
	{ minCh = DEFAULT_MIN_CH, maxCh = DEFAULT_MAX_CH }: { minCh?: number; maxCh?: number } = {},
): CSSProperties {
	const longest = [placeholder, ...labels].reduce((max, label) => Math.max(max, label.length), 0);
	const ch = Math.min(Math.max(longest, minCh), maxCh);
	return { width: `calc(${ch}ch + ${FILTER_WIDTH_PADDING_CH}ch)` };
}

export function dateRangeFilterWidthStyle(placeholder: string, hasValue: boolean): CSSProperties {
	return filterWidthStyle(hasValue ? [DATE_RANGE_VALUE_LABEL] : [], placeholder, {
		maxCh: DATE_RANGE_VALUE_LABEL.length,
	});
}
