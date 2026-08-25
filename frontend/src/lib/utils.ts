import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}

/** Business timezone for all clock timestamps shown in the UI. */
export const ACCORD_TIME_ZONE = "Asia/Kolkata";

/** Calendar date only: `YYYY-MM-DD`. Not accepted by {@link parseApiDateTime}. */
const DATE_ONLY_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Timezone-less API datetime: `YYYY-MM-DDTHH:mm[:ss[.fraction]]`.
 * Accord stores UTC-naive timestamps and serializes them without `Z`.
 */
const NAIVE_DATETIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;

const accordDatePartsFormatter = new Intl.DateTimeFormat("en-IN", {
	timeZone: ACCORD_TIME_ZONE,
	day: "2-digit",
	month: "short",
	year: "numeric",
});

const accordTimeFormatter = new Intl.DateTimeFormat("en-GB", {
	timeZone: ACCORD_TIME_ZONE,
	hour: "2-digit",
	minute: "2-digit",
	hour12: false,
});

/**
 * Parse an API clock timestamp as UTC.
 *
 * Timezone-less datetime strings (e.g. `2026-05-10T10:15:00`) are treated as
 * UTC. Date-only `YYYY-MM-DD` strings are rejected — use calendar-date helpers
 * for those. Strings that already carry `Z` or an offset are left unchanged.
 */
export function parseApiDateTime(value: Date | string | null | undefined): Date | null {
	if (value === null || value === undefined) return null;
	if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;

	const trimmed = value.trim();
	if (!trimmed || DATE_ONLY_RE.test(trimmed)) return null;

	const normalized = NAIVE_DATETIME_RE.test(trimmed) ? `${trimmed}Z` : trimmed;
	const date = new Date(normalized);
	return Number.isNaN(date.getTime()) ? null : date;
}

function formatAccordDateParts(date: Date): string {
	const parts = accordDatePartsFormatter.formatToParts(date);
	const day = (parts.find((part) => part.type === "day")?.value ?? "").padStart(2, "0");
	const month = parts.find((part) => part.type === "month")?.value ?? "";
	const year = parts.find((part) => part.type === "year")?.value ?? "";
	return `${day} ${month}, ${year}`;
}

/**
 * Format a date as "DD Mon, YYYY" (e.g. "26 Feb, 2026").
 * For calendar date-only values (`YYYY-MM-DD`) and local Date objects.
 * For API clock timestamps, use {@link formatDateTime} or {@link formatDateInAccordTimeZone}.
 */
export function formatDate(value: Date | string | null | undefined): string {
	if (value === null || value === undefined) return "-";
	let date: Date;
	if (typeof value === "string") {
		if (DATE_ONLY_RE.test(value)) {
			const [year, month, day] = value.split("-").map(Number);
			date = new Date(year, month - 1, day);
			if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
				return "-";
			}
		} else {
			date = new Date(value);
		}
	} else {
		date = value;
	}
	if (Number.isNaN(date.getTime())) return "-";

	const day = String(date.getDate()).padStart(2, "0");
	const month = date.toLocaleDateString("en-IN", { month: "short" });
	const year = date.getFullYear();
	return `${day} ${month}, ${year}`;
}

/** Format the calendar date of an API datetime in IST as "DD Mon, YYYY". */
export function formatDateInAccordTimeZone(value: Date | string | null | undefined): string {
	const date = parseApiDateTime(value);
	if (!date) return "-";
	return formatAccordDateParts(date);
}

/** Format a date-time as "DD Mon, YYYY, HH:mm" in IST. */
export function formatDateTime(value: Date | string | null | undefined): string {
	const date = parseApiDateTime(value);
	if (!date) return "-";
	return `${formatAccordDateParts(date)}, ${accordTimeFormatter.format(date)}`;
}

/** Format a byte count as a human-readable string (e.g. "1.2 MB"). */
export function formatFileSize(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
