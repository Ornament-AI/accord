import {
	type ColumnDef,
	getCoreRowModel,
	type RowData,
	useReactTable,
} from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import {
	ColumnVisibilityToggle,
	usePersistedColumnVisibility,
} from "@/components/column-visibility";
import { DataTableShell } from "@/components/data-table-shell";
import { DataTableSkeleton } from "@/components/data-table-skeleton";
import { EmptyState } from "@/components/empty-state";
import { PageSection, PageShell } from "@/components/page-shell";
import { Badge } from "@/components/ui/badge";
import {
	Breadcrumb,
	BreadcrumbItem,
	BreadcrumbLink,
	BreadcrumbList,
	BreadcrumbPage,
	BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/contexts/AuthContext";
import {
	type ComponentRateVersionResponse,
	calcKindLabel,
	classificationLabel,
	roundingRuleLabel,
	useComponentRateVersions,
	usePayComponent,
	usePayComponentsList,
} from "@/lib/api/pay-setup";
import { getErrorMessage } from "@/lib/errors";
import { formatDate } from "@/lib/utils";

import { CreateRateVersionDialog } from "./CreateRateVersionDialog";

declare module "@tanstack/react-table" {
	interface ColumnMeta<TData extends RowData, TValue> {
		align?: "left" | "right" | "center";
		className?: string;
	}
}

function PayComponentBreadcrumb({ label }: { label: string }) {
	return (
		<Breadcrumb>
			<BreadcrumbList>
				<BreadcrumbItem>
					<BreadcrumbLink render={<Link to="/pay-components" />}>Pay components</BreadcrumbLink>
				</BreadcrumbItem>
				<BreadcrumbSeparator />
				<BreadcrumbItem>
					<BreadcrumbPage>{label}</BreadcrumbPage>
				</BreadcrumbItem>
			</BreadcrumbList>
		</Breadcrumb>
	);
}

function formatEffectiveRange(version: ComponentRateVersionResponse): string {
	const from = formatDate(version.effective_from);
	const to = version.effective_to ? formatDate(version.effective_to) : "open-ended";
	return `${from} – ${to}`;
}

function formatRateOrAmount(version: ComponentRateVersionResponse): string {
	if (version.amount != null && version.amount !== "") return version.amount;
	if (version.rate != null && version.rate !== "") return version.rate;
	return "—";
}

const rateVersionColumns: ColumnDef<ComponentRateVersionResponse>[] = [
	{
		id: "effective_range",
		header: "Effective range",
		cell: ({ row }) => formatEffectiveRange(row.original),
	},
	{
		accessorKey: "calc_kind",
		header: "Calc kind",
		cell: ({ row }) => calcKindLabel(row.original.calc_kind),
	},
	{
		id: "rate_or_amount",
		header: "Rate / amount",
		cell: ({ row }) => formatRateOrAmount(row.original),
	},
	{
		accessorKey: "rounding_rule",
		header: "Rounding rule",
		cell: ({ row }) => roundingRuleLabel(row.original.rounding_rule),
	},
];

export default function PayComponentDetailPage() {
	const { componentId } = useParams<{ componentId: string }>();
	const { hasCapability } = useAuth();
	const canManage = hasCapability("manage_master_data");
	const [createOpen, setCreateOpen] = useState(false);

	const [columnVisibility, setColumnVisibility] = usePersistedColumnVisibility(
		"accord:pay-component-rate-versions:columns",
		{},
	);

	const componentQuery = usePayComponent(componentId);
	const rateVersionsQuery = useComponentRateVersions(componentId);
	const allComponentsQuery = usePayComponentsList();

	const component = componentQuery.data;
	const rateVersions = rateVersionsQuery.data ?? [];

	const basisOptions = useMemo(
		() =>
			(allComponentsQuery.data ?? []).filter((item) => item.id !== componentId && item.is_active),
		[allComponentsQuery.data, componentId],
	);

	const table = useReactTable({
		data: rateVersions,
		columns: rateVersionColumns,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.id,
		state: { columnVisibility },
		onColumnVisibilityChange: setColumnVisibility,
	});

	if (!componentId) {
		return (
			<CapabilityGate capability="view_master_data" title="Pay component">
				<AppLayout title="Pay component">
					<PageShell>
						<EmptyState title="Pay component not found" description="Missing component id." />
					</PageShell>
				</AppLayout>
			</CapabilityGate>
		);
	}

	return (
		<CapabilityGate capability="view_master_data" title="Pay component">
			<AppLayout
				title={component ? <PayComponentBreadcrumb label={component.code} /> : "Pay component"}
				actions={
					canManage ? (
						<Button size="xs" onClick={() => setCreateOpen(true)}>
							Add
						</Button>
					) : undefined
				}
			>
				<PageShell data-testid="pay-component-detail-page">
					{componentQuery.isLoading ? (
						<div className="grid gap-4">
							<Skeleton className="h-20 w-full" />
							<DataTableSkeleton />
						</div>
					) : null}

					{componentQuery.isError ? (
						<ErrorWithRetry
							message={getErrorMessage(componentQuery.error, "Failed to load pay component.")}
							onRetry={() => void componentQuery.refetch()}
						/>
					) : null}

					{component ? (
						<>
							<PageSection>
								<div className="flex flex-wrap items-center gap-3">
									<h2 className="text-xl font-semibold tracking-tight">{component.code}</h2>
									<span className="text-muted-foreground">{component.name}</span>
									<Badge variant="secondary">{classificationLabel(component.classification)}</Badge>
									<Badge variant={component.is_active ? "default" : "outline"}>
										{component.is_active ? "Active" : "Inactive"}
									</Badge>
								</div>
							</PageSection>

							<PageSection className="grid gap-3">
								<div className="flex flex-wrap items-center justify-between gap-2">
									<h3 className="text-sm font-medium">Rate version history</h3>
									<ColumnVisibilityToggle
										table={table}
										iconOnly
										triggerClassName="justify-center"
									/>
								</div>

								{rateVersionsQuery.isLoading ? <DataTableSkeleton /> : null}

								{rateVersionsQuery.isError ? (
									<ErrorWithRetry
										message={getErrorMessage(
											rateVersionsQuery.error,
											"Failed to load rate versions.",
										)}
										onRetry={() => void rateVersionsQuery.refetch()}
									/>
								) : null}

								{!rateVersionsQuery.isLoading &&
								!rateVersionsQuery.isError &&
								rateVersions.length === 0 ? (
									<p className="text-sm text-muted-foreground">No rate versions yet.</p>
								) : null}

								{!rateVersionsQuery.isLoading &&
								!rateVersionsQuery.isError &&
								rateVersions.length > 0 ? (
									<DataTableShell table={table} />
								) : null}
							</PageSection>
						</>
					) : null}
				</PageShell>

				{canManage && component ? (
					<CreateRateVersionDialog
						open={createOpen}
						onOpenChange={setCreateOpen}
						componentId={component.id}
						basisOptions={basisOptions}
					/>
				) : null}
			</AppLayout>
		</CapabilityGate>
	);
}
