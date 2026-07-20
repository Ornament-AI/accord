import { useOutletContext, useParams } from "react-router";

import { EmptyState } from "@/components/empty-state";
import { PageSkeleton } from "@/components/page-skeleton";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { useReportPreview } from "@/lib/api/reports";
import { getErrorMessage } from "@/lib/errors";
import { FileXIcon as FileX } from "@phosphor-icons/react/dist/csr/FileX";

import { ReportPreviewTables } from "./ReportPreviewTables";
import type { ReportsOutletContext } from "./ReportsLayout";
import { productSheetBySlug } from "@/lib/reports/report-registry";

export default function ReportSheetPage() {
	const { reportSlug = "" } = useParams<{ reportSlug: string }>();
	const { selectedRunId } = useOutletContext<ReportsOutletContext>();
	const sheet = productSheetBySlug(reportSlug);

	const previewQuery = useReportPreview(sheet?.reportType, selectedRunId);

	if (!sheet) {
		return (
			<EmptyState
				icon={FileX}
				title="Unknown Report"
				description="This report sheet is not part of the product catalog."
			/>
		);
	}

	if (!selectedRunId) {
		return (
			<p className="text-muted-foreground text-sm" data-testid="report-sheet-needs-run">
				Select a posted run to preview {sheet.title}.
			</p>
		);
	}

	if (previewQuery.isLoading) {
		return <PageSkeleton />;
	}

	if (previewQuery.isError) {
		return (
			<ErrorWithRetry
				message={getErrorMessage(previewQuery.error, "Failed to load report preview.")}
				onRetry={() => void previewQuery.refetch()}
			/>
		);
	}

	if (!previewQuery.data) {
		return null;
	}

	return (
		<div data-testid={`report-sheet-${sheet.reportType}`}>
			<ReportPreviewTables preview={previewQuery.data} />
		</div>
	);
}
