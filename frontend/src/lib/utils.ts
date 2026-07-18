import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}

export const RUPEES_PER_CRORE = 10_000_000n;
const PAISE_PER_RUPEE = 100n;
const PAISE_PER_CRORE = RUPEES_PER_CRORE * PAISE_PER_RUPEE;

export function rupeesStringToCroresString(value: string | null | undefined): string {
	if (value === null || value === undefined) return "";
	const match = value.trim().match(/^(\d+)(?:\.(\d{1,2}))?$/);
	if (!match) return "";

	const rupees = BigInt(match[1]);
	const paise = BigInt((match[2] ?? "").padEnd(2, "0"));
	const totalPaise = rupees * PAISE_PER_RUPEE + paise;
	const crore = totalPaise / PAISE_PER_CRORE;
	const remainder = totalPaise % PAISE_PER_CRORE;
	if (remainder === 0n) return crore.toString();

	const fractionalCrore = remainder.toString().padStart(9, "0").replace(/0+$/, "");
	return `${crore}.${fractionalCrore}`;
}

export function formatCurrency(value: number | string | null | undefined): string {
	if (value === null || value === undefined) return "-";
	const num = typeof value === "string" ? Number.parseFloat(value) : value;
	if (Number.isNaN(num)) return "-";
	if (num === 0) return "₹0";

	const isNegative = num < 0;
	const absFormatted = Math.abs(num).toLocaleString("en-IN", {
		style: "currency",
		currency: "INR",
		minimumFractionDigits: 0,
		maximumFractionDigits: 0,
	});

	return isNegative ? absFormatted.replace("\u20B9", "\u20B9-") : absFormatted;
}

export function formatCurrencyCompact(value: number | string | null | undefined): string {
	if (value === null || value === undefined) return "-";
	const num = typeof value === "string" ? Number.parseFloat(value) : value;
	if (Number.isNaN(num)) return "-";
	if (num === 0) return "₹0";

	const isNegative = num < 0;
	const abs = Math.abs(num);
	const sign = isNegative ? "-" : "";
	const rupeesPerCrore = Number(RUPEES_PER_CRORE);

	if (abs >= rupeesPerCrore) {
		return `\u20B9${sign}${(abs / rupeesPerCrore).toFixed(2)} Cr`;
	}
	if (abs >= 100000) {
		return `\u20B9${sign}${(abs / 100000).toFixed(2)} L`;
	}
	return `\u20B9${sign}${abs.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
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

/** Format a value already in crores as "₹X,XXX Cr" or "₹X,XXX.XX Cr". */
export function formatCrores(value: number | string | null | undefined): string {
	if (value === null || value === undefined) return "—";
	const num = typeof value === "string" ? Number.parseFloat(value) : value;
	if (Number.isNaN(num)) return "—";
	if (num === 0) return "₹0 Cr";

	const isNegative = num < 0;
	const abs = Math.abs(num);
	const sign = isNegative ? "-" : "";
	const hasDecimals = abs % 1 >= 0.005;
	const formatted = abs.toLocaleString("en-IN", {
		minimumFractionDigits: hasDecimals ? 2 : 0,
		maximumFractionDigits: hasDecimals ? 2 : 0,
	});
	return `\u20B9${sign}${formatted} Cr`;
}
