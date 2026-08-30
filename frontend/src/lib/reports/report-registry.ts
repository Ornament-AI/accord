/**
 * Frontend report routes joined to the backend-generated product catalog.
 * Membership, order, and titles come from the canonical backend allowlist.
 */

import backendProductReportSheets from "./report-catalog.generated.json";

export type ProductReportSheet = {
	reportType: string;
	slug: string;
	title: string;
};

/** Frontend-owned URL slugs, in canonical backend product-surface order. */
const PRODUCT_REPORT_ROUTES = [
	{ reportType: "pay_bill", slug: "pay-bill" },
	{ reportType: "treasury_face", slug: "treasury-face" },
	{ reportType: "bank_rtgs_advice", slug: "bank-rtgs-advice" },
	{ reportType: "payslips", slug: "payslips" },
	{ reportType: "gpf_mumbai_schedule", slug: "gpf-mumbai-schedule" },
	{ reportType: "gpf_nagpur_schedule", slug: "gpf-nagpur-schedule" },
	{ reportType: "nps_contribution_schedule", slug: "nps-contribution-schedule" },
	{ reportType: "income_tax_schedule", slug: "income-tax-schedule" },
	{ reportType: "professional_tax_schedule", slug: "professional-tax-schedule" },
	{ reportType: "gis_schedule", slug: "gis-schedule" },
	{ reportType: "hba_schedule", slug: "hba-schedule" },
	{ reportType: "gpf_advance_schedule", slug: "gpf-advance-schedule" },
	{ reportType: "motor_car_advance_schedule", slug: "motor-car-advance-schedule" },
	{ reportType: "motorcycle_advance_schedule", slug: "motorcycle-advance-schedule" },
	{ reportType: "festival_advance_schedule", slug: "festival-advance-schedule" },
	{ reportType: "accommodation_mumbai_schedule", slug: "accommodation-mumbai-schedule" },
	{ reportType: "accommodation_worli_schedule", slug: "accommodation-worli-schedule" },
	{ reportType: "approval_note", slug: "approval-note" },
] as const;

if (
	backendProductReportSheets.length !== PRODUCT_REPORT_ROUTES.length ||
	backendProductReportSheets.some(
		(sheet, index) => sheet.report_type !== PRODUCT_REPORT_ROUTES[index]?.reportType,
	)
) {
	throw new Error(
		"Frontend report routes do not match the generated backend product-report catalog.",
	);
}

export const PRODUCT_REPORT_SHEETS: readonly ProductReportSheet[] = backendProductReportSheets.map(
	(sheet, index) => ({
		reportType: sheet.report_type,
		slug: PRODUCT_REPORT_ROUTES[index]!.slug,
		title: sheet.title,
	}),
);

const BY_SLUG = new Map(PRODUCT_REPORT_SHEETS.map((sheet) => [sheet.slug, sheet]));

export function productSheetBySlug(slug: string): ProductReportSheet | undefined {
	return BY_SLUG.get(slug);
}

export function firstProductSheetSlug(): string {
	return PRODUCT_REPORT_SHEETS[0]!.slug;
}
