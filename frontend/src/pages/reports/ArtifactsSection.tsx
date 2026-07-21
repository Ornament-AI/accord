import { CircleNotchIcon as Loader2 } from "@phosphor-icons/react/dist/csr/CircleNotch";
import { DownloadSimpleIcon as Download } from "@phosphor-icons/react/dist/csr/DownloadSimple";
import { FilesIcon as FileStack } from "@phosphor-icons/react/dist/csr/Files";
import {
	type ColumnDef,
	getCoreRowModel,
	type RowData,
	useReactTable,
} from "@tanstack/react-table";
import { useMemo } from "react";

import {
	ColumnVisibilityToggle,
	usePersistedColumnVisibility,
} from "@/components/column-visibility";
import { DataTableShell } from "@/components/data-table-shell";
import { EmptyState } from "@/components/empty-state";
import { PageSection } from "@/components/page-shell";
import { PageSkeleton } from "@/components/page-skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import type { PayrollRunListItem } from "@/lib/api/payroll-runs";
import { type ArtifactResponse, useDownloadArtifact } from "@/lib/api/reports";
import { getErrorMessage } from "@/lib/errors";
import { periodLabel } from "@/lib/payroll-display";
import { formatDateTime, formatFileSize } from "@/lib/utils";

declare module "@tanstack/react-table" {
	interface ColumnMeta<TData extends RowData, TValue> {
		align?: "left" | "right" | "center";
		className?: string;
	}
}

function runLabel(
	runsById: Map<string, PayrollRunListItem>,
	postedRunId: string | null | undefined,
): string {
	if (!postedRunId) return "—";
	const run = runsById.get(postedRunId);
	if (!run) return postedRunId.slice(0, 8);
	return periodLabel(run.period_year, run.period_month);
}

function DownloadArtifactButton({ artifactId }: { artifactId: string }) {
	const downloadMutation = useDownloadArtifact();
	return (
		<Button
			type="button"
			size="sm"
			variant="ghost"
			aria-label={`Download artifact ${artifactId}`}
			disabled={downloadMutation.isPending}
			onClick={() => void downloadMutation.mutateAsync(artifactId)}
		>
			{downloadMutation.isPending ? (
				<Loader2 className="size-4 animate-spin" aria-hidden="true" />
			) : (
				<Download className="size-4" aria-hidden="true" />
			)}
			Download
		</Button>
	);
}

type ArtifactsSectionProps = {
	items: ArtifactResponse[] | undefined;
	isLoading: boolean;
	isError: boolean;
	error: unknown;
	onRetry: () => void;
	runs: PayrollRunListItem[];
	selectedRunId: string | null;
	page?: number;
	totalPages?: number;
	onPageChange?: (page: number) => void;
};

export function ArtifactsSection({
	items,
	isLoading,
	isError,
	error,
	onRetry,
	runs,
	selectedRunId,
	page,
	totalPages,
	onPageChange,
}: ArtifactsSectionProps) {
	const [columnVisibility, setColumnVisibility] = usePersistedColumnVisibility(
		"accord:artifacts:columns",
		{},
	);

	const runsById = useMemo(() => new Map(runs.map((run) => [run.id, run])), [runs]);

	const columns = useMemo<ColumnDef<ArtifactResponse>[]>(
		() => [
			{
				accessorKey: "report_type",
				header: "Type",
				cell: ({ row }) => <span className="font-mono text-xs">{row.original.report_type}</span>,
			},
			{
				id: "run",
				header: "Run",
				cell: ({ row }) => runLabel(runsById, row.original.posted_run_id),
			},
			{
				accessorKey: "size_bytes",
				header: "Size",
				meta: { align: "right" },
				cell: ({ row }) => formatFileSize(row.original.size_bytes),
			},
			{
				accessorKey: "created_at",
				header: "Created",
				cell: ({ row }) => formatDateTime(row.original.created_at),
			},
			{
				accessorKey: "status",
				header: "Status",
				cell: ({ row }) => <Badge variant="secondary">{row.original.status}</Badge>,
			},
			{
				id: "actions",
				header: "Actions",
				enableHiding: false,
				meta: { hideFromColumnVisibilityToggle: true },
				cell: ({ row }) => <DownloadArtifactButton artifactId={row.original.id} />,
			},
		],
		[runsById],
	);

	const table = useReactTable({
		data: items ?? [],
		columns,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.id,
		state: { columnVisibility },
		onColumnVisibilityChange: setColumnVisibility,
	});

	return (
		<PageSection data-testid="artifacts-section" className="flex flex-col gap-3">
			<div className="flex flex-wrap items-start justify-between gap-2">
				<div>
					<h2 className="text-base font-semibold tracking-tight">Recent Artifacts</h2>
					<p className="text-muted-foreground text-sm">
						{selectedRunId
							? "Artifacts for the selected posted run."
							: "Recent export artifacts across posted runs."}
					</p>
				</div>
				<ColumnVisibilityToggle table={table} iconOnly triggerClassName="justify-center" />
			</div>

			{isLoading ? <PageSkeleton /> : null}

			{isError ? (
				<ErrorWithRetry
					message={getErrorMessage(error, "Failed to load artifacts.")}
					onRetry={onRetry}
				/>
			) : null}

			{!isLoading && !isError && (items?.length ?? 0) === 0 ? (
				<EmptyState
					icon={FileStack}
					title="No Artifacts Yet"
					description={
						selectedRunId
							? "Generate a report for this posted run to create an artifact."
							: "Generated report files will appear here."
					}
				/>
			) : null}

			{!isLoading && !isError && (items?.length ?? 0) > 0 ? (
				<DataTableShell
					table={table}
					page={page}
					totalPages={totalPages}
					onPageChange={onPageChange}
				/>
			) : null}
		</PageSection>
	);
}
