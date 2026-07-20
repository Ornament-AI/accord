/**
 * Frontend product-sheet titles / slugs. Canonical membership is the backend
 * catalog (`product_sheet: true`); tests assert FE keys ⊆ catalog product sheets.
 */

export type ProductReportSheet = {
	reportType: string;
	slug: string;
	title: string;
};

/** Stable product-surface order (mirrors backend PRODUCT_REPORT_SHEETS). */
export const PRODUCT_REPORT_SHEETS: readonly ProductReportSheet[] = [
	{ reportType: "pay_bill", slug: "pay-bill", title: "Pay Bill" },
	{ reportType: "treasury_face", slug: "treasury-face", title: "Treasury Face" },
	{
		reportType: "bank_rtgs_advice",
		slug: "bank-rtgs-advice",
		title: "Bank RTGS Advice",
	},
	{ reportType: "payslips", slug: "payslips", title: "Payslips" },
	{
		reportType: "gpf_mumbai_schedule",
		slug: "gpf-mumbai-schedule",
		title: "GPF Mumbai Schedule",
	},
	{
		reportType: "gpf_nagpur_schedule",
		slug: "gpf-nagpur-schedule",
		title: "GPF Nagpur Schedule",
	},
	{
		reportType: "nps_contribution_schedule",
		slug: "nps-contribution-schedule",
		title: "NPS Contribution Schedule",
	},
	{
		reportType: "income_tax_schedule",
		slug: "income-tax-schedule",
		title: "Income Tax Schedule",
	},
	{
		reportType: "professional_tax_schedule",
		slug: "professional-tax-schedule",
		title: "Professional Tax Schedule",
	},
	{ reportType: "gis_schedule", slug: "gis-schedule", title: "GIS Schedule" },
	{ reportType: "hba_schedule", slug: "hba-schedule", title: "HBA Schedule" },
	{
		reportType: "gpf_advance_schedule",
		slug: "gpf-advance-schedule",
		title: "GPF Advance Schedule",
	},
	{
		reportType: "motor_car_advance_schedule",
		slug: "motor-car-advance-schedule",
		title: "Motor Car Advance Schedule",
	},
	{
		reportType: "motorcycle_advance_schedule",
		slug: "motorcycle-advance-schedule",
		title: "Motorcycle Advance Schedule",
	},
	{
		reportType: "festival_advance_schedule",
		slug: "festival-advance-schedule",
		title: "Festival Advance Schedule",
	},
	{
		reportType: "accommodation_mumbai_schedule",
		slug: "accommodation-mumbai-schedule",
		title: "Accommodation Mumbai Schedule",
	},
	{
		reportType: "accommodation_worli_schedule",
		slug: "accommodation-worli-schedule",
		title: "Accommodation Worli Schedule",
	},
	{ reportType: "approval_note", slug: "approval-note", title: "Approval Note" },
] as const;

const BY_SLUG = new Map(PRODUCT_REPORT_SHEETS.map((sheet) => [sheet.slug, sheet]));
const BY_TYPE = new Map(PRODUCT_REPORT_SHEETS.map((sheet) => [sheet.reportType, sheet]));

export function productSheetBySlug(slug: string): ProductReportSheet | undefined {
	return BY_SLUG.get(slug);
}

export function productSheetByType(reportType: string): ProductReportSheet | undefined {
	return BY_TYPE.get(reportType);
}

export function firstProductSheetSlug(): string {
	return PRODUCT_REPORT_SHEETS[0]!.slug;
}

export function reportTypeToSlug(reportType: string): string {
	return BY_TYPE.get(reportType)?.slug ?? reportType.replaceAll("_", "-");
}
