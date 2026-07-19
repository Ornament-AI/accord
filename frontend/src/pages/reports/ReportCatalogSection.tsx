import { ChartBarIcon as FileBarChart2 } from "@phosphor-icons/react/dist/csr/ChartBar";

import { DataTableSkeleton } from "@/components/data-table-skeleton";
import { EmptyState } from "@/components/empty-state";
import { PageSection } from "@/components/page-shell";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import type { ReportCatalogEntry } from "@/lib/api/reports";
import { getErrorMessage } from "@/lib/errors";

import { GenerationControls } from "./GenerationControls";
import { groupReportCatalog, reportTypeTitle } from "./report-families";
import type { ReportGenerationController } from "./use-report-generation";

type ReportCatalogSectionProps = {
	entries: ReportCatalogEntry[] | undefined;
	isLoading: boolean;
	isError: boolean;
	error: unknown;
	onRetry: () => void;
	postedRunId: string | null;
	generationDisabled?: boolean;
	generation: ReportGenerationController;
};

export function ReportCatalogSection({
	entries,
	isLoading,
	isError,
	error,
	onRetry,
	postedRunId,
	generationDisabled = false,
	generation,
}: ReportCatalogSectionProps) {
	if (isLoading) return <DataTableSkeleton rows={4} />;

	if (isError) {
		return (
			<ErrorWithRetry
				message={getErrorMessage(error, "Failed to load report catalog.")}
				onRetry={onRetry}
			/>
		);
	}

	const catalog = entries ?? [];
	if (catalog.length === 0) {
		return (
			<EmptyState
				icon={FileBarChart2}
				title="No report types"
				description="No report types are available for this organization yet."
			/>
		);
	}

	const groups = groupReportCatalog(catalog);

	return (
		<PageSection data-testid="report-catalog" className="flex flex-col gap-6">
			{groups.map((group) => (
				<div
					key={group.family}
					data-testid={`report-family-${group.family}`}
					className="flex flex-col gap-3"
				>
					<h3 className="text-sm font-semibold tracking-tight">{group.title}</h3>
					<ul className="divide-border divide-y rounded-lg border">
						{group.entries.map((entry) => (
							<li
								key={entry.report_type}
								className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
								data-testid={`report-type-${entry.report_type}`}
							>
								<div className="min-w-0">
									<p className="font-medium">{reportTypeTitle(entry)}</p>
									<p className="text-muted-foreground font-mono text-xs">{entry.report_type}</p>
								</div>
								<GenerationControls
									entry={entry}
									postedRunId={postedRunId}
									disabled={generationDisabled}
									generation={generation}
								/>
							</li>
						))}
					</ul>
				</div>
			))}
		</PageSection>
	);
}
