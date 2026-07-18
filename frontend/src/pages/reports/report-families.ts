import type { ReportCatalogEntry, ReportFormat } from "@/lib/api/reports";

/** Known report families matched by report_type prefix (dotted or underscore). */
export const REPORT_FAMILY_PREFIXES = [
	"payroll_register",
	"payments",
	"retirement",
	"statutory",
	"recovery",
	"accommodation",
	"approval",
] as const;

export type ReportFamilyKey = (typeof REPORT_FAMILY_PREFIXES)[number] | "other";

/** Formats surfaced as generation buttons on the Reports page. */
export const REPORT_UI_FORMATS: ReportFormat[] = ["excel", "pdf"];

export function reportFamilyKey(reportType: string): ReportFamilyKey {
	const dotted = reportType.split(".")[0]?.toLowerCase() ?? "";
	if ((REPORT_FAMILY_PREFIXES as readonly string[]).includes(dotted)) {
		return dotted as ReportFamilyKey;
	}

	const sorted = [...REPORT_FAMILY_PREFIXES].sort((a, b) => b.length - a.length);
	for (const family of sorted) {
		if (reportType === family || reportType.startsWith(`${family}_`)) {
			return family;
		}
	}
	return "other";
}

export function familyTitle(family: ReportFamilyKey): string {
	if (family === "other") return "Other";
	return family
		.split("_")
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

export function reportTypeTitle(entry: ReportCatalogEntry): string {
	if (entry.title?.trim()) return entry.title.trim();
	const leaf = entry.report_type.includes(".")
		? (entry.report_type.split(".").at(-1) ?? entry.report_type)
		: entry.report_type;
	return leaf
		.split("_")
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

export function formatButtonLabel(format: ReportFormat): string {
	switch (format) {
		case "excel":
			return "Excel";
		case "pdf":
			return "PDF";
		case "json":
			return "JSON";
	}
}

export type ReportFamilyGroup = {
	family: ReportFamilyKey;
	title: string;
	entries: ReportCatalogEntry[];
};

/** Group catalog entries by family prefix; preserve first-seen family order, then Other. */
export function groupReportCatalog(entries: ReportCatalogEntry[]): ReportFamilyGroup[] {
	const buckets = new Map<ReportFamilyKey, ReportCatalogEntry[]>();
	const order: ReportFamilyKey[] = [];

	for (const entry of entries) {
		const family = reportFamilyKey(entry.report_type);
		if (!buckets.has(family)) {
			buckets.set(family, []);
			order.push(family);
		}
		buckets.get(family)!.push(entry);
	}

	const preferred = REPORT_FAMILY_PREFIXES.filter((family) => buckets.has(family));
	const rest = order.filter(
		(family) =>
			family === "other" || !(REPORT_FAMILY_PREFIXES as readonly string[]).includes(family),
	);
	const sortedOrder = [
		...preferred,
		...rest.filter((f) => f !== "other"),
		...rest.filter((f) => f === "other"),
	];

	return sortedOrder.map((family) => ({
		family,
		title: familyTitle(family),
		entries: buckets.get(family) ?? [],
	}));
}

export function availableUiFormats(entry: ReportCatalogEntry): ReportFormat[] {
	return REPORT_UI_FORMATS.filter((format) => entry.formats.includes(format));
}

export function generationSlotKey(reportType: string, format: ReportFormat): string {
	return `${reportType}:${format}`;
}
