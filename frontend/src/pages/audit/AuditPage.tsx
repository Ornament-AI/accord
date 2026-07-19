import { ClipboardTextIcon as ClipboardList } from "@phosphor-icons/react/dist/csr/ClipboardText";
import {
	type ColumnDef,
	getCoreRowModel,
	type RowData,
	useReactTable,
} from "@tanstack/react-table";
import { useEffect, useMemo, useState } from "react";
import type { DateRange } from "react-day-picker";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { DataTableShell } from "@/components/data-table-shell";
import { DataTableSkeleton } from "@/components/data-table-skeleton";
import { EmptyState } from "@/components/empty-state";
import { PageShell } from "@/components/page-shell";
import { PageToolbar } from "@/components/page-toolbar";
import { DateRangePicker } from "@/components/ui/date-range-picker";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Input } from "@/components/ui/input";
import {
	Sheet,
	SheetContent,
	SheetDescription,
	SheetHeader,
	SheetTitle,
} from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import { type AuditEventResponse, toAuditDayBound, useAuditEventsList } from "@/lib/api/audit";
import { getErrorMessage } from "@/lib/errors";
import { dateRangeFilterWidthStyle, filterWidthStyle } from "@/lib/filter-width";
import { cn, formatDateTime } from "@/lib/utils";

import { AuditEventDetail } from "./AuditEventDetail";
import { CommandBadge } from "./CommandBadge";

declare module "@tanstack/react-table" {
	interface ColumnMeta<TData extends RowData, TValue> {
		align?: "left" | "right" | "center";
		className?: string;
	}
}

const PAGE_SIZE = 20;

function useDebouncedValue<T>(value: T, delayMs: number): T {
	const [debounced, setDebounced] = useState(value);
	useEffect(() => {
		const handle = window.setTimeout(() => setDebounced(value), delayMs);
		return () => window.clearTimeout(handle);
	}, [value, delayMs]);
	return debounced;
}

function actorLabel(event: AuditEventResponse): string {
	if (!event.actor) return "System";
	return event.actor.name?.trim() || event.actor.email?.trim() || "System";
}

function buildColumns(selectedId: string | null): ColumnDef<AuditEventResponse>[] {
	return [
		{
			accessorKey: "created_at",
			header: "When",
			cell: ({ row }) => (
				<span className={cn(row.original.id === selectedId && "font-medium")}>
					{formatDateTime(row.original.created_at)}
				</span>
			),
		},
		{
			accessorKey: "command",
			header: "Command",
			cell: ({ row }) => <CommandBadge command={row.original.command} />,
		},
		{
			id: "entity",
			header: "Entity",
			cell: ({ row }) => (
				<span className="text-muted-foreground">
					{row.original.entity_type}
					<span className="mx-1 text-border">·</span>
					<span className="font-mono text-xs">{row.original.entity_id.slice(0, 8)}</span>
				</span>
			),
		},
		{
			id: "actor",
			header: "Actor",
			cell: ({ row }) => actorLabel(row.original),
		},
	];
}

export default function AuditPage() {
	const isMobile = useIsMobile();

	const [command, setCommand] = useState("");
	const [entityType, setEntityType] = useState("");
	const [entityId, setEntityId] = useState("");
	const [dateRange, setDateRange] = useState<DateRange | undefined>();
	const [page, setPage] = useState(1);
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [sheetOpen, setSheetOpen] = useState(false);

	const debouncedCommand = useDebouncedValue(command, 300);
	const debouncedEntityType = useDebouncedValue(entityType, 300);
	const debouncedEntityId = useDebouncedValue(entityId, 300);

	const listParams = useMemo(
		() => ({
			command: debouncedCommand.trim() || null,
			entity_type: debouncedEntityType.trim() || null,
			entity_id: debouncedEntityId.trim() || null,
			from: dateRange?.from ? toAuditDayBound(dateRange.from, "start") : null,
			to: dateRange?.to
				? toAuditDayBound(dateRange.to, "end")
				: dateRange?.from
					? toAuditDayBound(dateRange.from, "end")
					: null,
			page,
			page_size: PAGE_SIZE,
		}),
		[debouncedCommand, debouncedEntityType, debouncedEntityId, dateRange, page],
	);

	const listQuery = useAuditEventsList(listParams);

	const columns = useMemo(() => buildColumns(selectedId), [selectedId]);
	const table = useReactTable({
		data: listQuery.data?.items ?? [],
		columns,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.id,
	});

	const totalPages = listQuery.data?.total_pages ?? 1;
	const isEmpty = !listQuery.isLoading && (listQuery.data?.items.length ?? 0) === 0;
	const hasEvents = !listQuery.isLoading && !listQuery.isError && !isEmpty;

	const selectEvent = (event: AuditEventResponse) => {
		setSelectedId(event.id);
		if (isMobile) {
			setSheetOpen(true);
		}
	};

	return (
		<CapabilityGate capability="view_audit" title="Audit">
			<AppLayout title="Audit">
				<PageShell data-testid="audit-page">
					<PageToolbar>
						<Input
							value={command}
							onChange={(event) => {
								setCommand(event.target.value);
								setPage(1);
							}}
							placeholder="Command…"
							aria-label="Filter by Command"
							style={filterWidthStyle([], "Command…")}
						/>
						<Input
							value={entityType}
							onChange={(event) => {
								setEntityType(event.target.value);
								setPage(1);
							}}
							placeholder="Entity type…"
							aria-label="Filter by Entity Type"
							style={filterWidthStyle([], "Entity type…")}
						/>
						<Input
							value={entityId}
							onChange={(event) => {
								setEntityId(event.target.value);
								setPage(1);
							}}
							placeholder="Entity ID…"
							aria-label="Search by Entity ID"
							style={filterWidthStyle([], "Entity ID…", { maxCh: 20 })}
						/>
						<DateRangePicker
							value={dateRange}
							onValueChange={(range) => {
								setDateRange(range);
								setPage(1);
							}}
							aria-label="Filter by Date Range"
							placeholder="Date range"
							numberOfMonths={isMobile ? 1 : 2}
							style={dateRangeFilterWidthStyle("Date range", Boolean(dateRange?.from))}
						/>
					</PageToolbar>

					<div
						className={cn(
							"grid min-h-0 flex-1 gap-4",
							hasEvents && "md:grid-cols-[minmax(0,1fr)_minmax(18rem,24rem)]",
						)}
					>
						<div className="min-w-0">
							{listQuery.isLoading ? <DataTableSkeleton /> : null}

							{listQuery.isError ? (
								<ErrorWithRetry
									message={getErrorMessage(listQuery.error, "Failed to load audit events.")}
									onRetry={() => void listQuery.refetch()}
								/>
							) : null}

							{!listQuery.isLoading && !listQuery.isError && isEmpty ? (
								<EmptyState
									icon={ClipboardList}
									title="No audit events"
									description="No events match the current filters."
								/>
							) : null}

							{!listQuery.isLoading && !listQuery.isError && !isEmpty ? (
								<DataTableShell
									table={table}
									isPlaceholderData={listQuery.isPlaceholderData}
									page={page}
									totalPages={totalPages}
									onPageChange={setPage}
									onRowClick={selectEvent}
									getRowAriaLabel={(row) =>
										`View audit event ${row.command} at ${formatDateTime(row.created_at)}`
									}
								/>
							) : null}
						</div>

						{hasEvents ? (
							<aside
								className="hidden min-h-0 rounded-lg border app-border-level-1 bg-card p-4 md:block"
								data-testid="audit-detail-panel"
							>
								<AuditEventDetail eventId={selectedId} />
							</aside>
						) : null}
					</div>
				</PageShell>

				<Sheet
					open={sheetOpen}
					onOpenChange={(open) => {
						setSheetOpen(open);
						if (!open && isMobile) {
							setSelectedId(null);
						}
					}}
				>
					<SheetContent side="right" className="w-full sm:max-w-md">
						<SheetHeader>
							<SheetTitle>Audit Event</SheetTitle>
							<SheetDescription>Details for the selected audit event.</SheetDescription>
						</SheetHeader>
						<div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
							<AuditEventDetail eventId={selectedId} />
						</div>
					</SheetContent>
				</Sheet>
			</AppLayout>
		</CapabilityGate>
	);
}
