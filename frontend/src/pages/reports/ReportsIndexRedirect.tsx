import { Navigate, useSearchParams } from "react-router";

import { firstProductSheetSlug } from "@/lib/reports/report-registry";

/** Index route: redirect to the first product sheet, preserving ``runId``. */
export default function ReportsIndexRedirect() {
	const [searchParams] = useSearchParams();
	const qs = searchParams.toString();
	return <Navigate to={`/reports/${firstProductSheetSlug()}${qs ? `?${qs}` : ""}`} replace />;
}
