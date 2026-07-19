import { ClipboardTextIcon as ClipboardList } from "@phosphor-icons/react/dist/csr/ClipboardText";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { DateRange } from "react-day-picker";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { EmptyState } from "@/components/empty-state";
import { PageShell } from "@/components/page-shell";
import { PaginationControls } from "@/components/pagination-controls";
import { Button } from "@/components/ui/button";
import {
	Combobox,
	ComboboxContent,
	ComboboxEmpty,
	ComboboxInput,
	ComboboxItem,
	ComboboxList,
} from "@/components/ui/combobox";
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
import { Skeleton } from "@/components/ui/skeleton";
import {
	type AuditActor,
	type AuditEventListItem,
	toAuditDayBound,
	useAuditEventsList,
	useAuditFilterOptions,
} from "@/lib/api/audit";
import { getErrorMessage } from "@/lib/errors";
import { cn, formatDateInAccordTimeZone, formatDateTime } from "@/lib/utils";

import { AuditEventDetail } from "./AuditEventDetail";

const PAGE_SIZE = 20;
const DESKTOP_QUERY = "(min-width: 1024px)";

function useDesktopLayout() {
	return useSyncExternalStore(
		(callback) => {
			const query = window.matchMedia(DESKTOP_QUERY);
			query.addEventListener("change", callback);
			return () => query.removeEventListener("change", callback);
		},
		() => window.innerWidth >= 1024,
		() => true,
	);
}

function useDebouncedValue<T>(value: T, delayMs: number): T {
	const [debounced, setDebounced] = useState(value);
	useEffect(() => {
		const handle = window.setTimeout(() => setDebounced(value), delayMs);
		return () => window.clearTimeout(handle);
	}, [value, delayMs]);
	return debounced;
}

function humanize(value: string): string {
	return value
		.replaceAll("_", " ")
		.replaceAll(".", " ")
		.replace(/^./, (character) => character.toUpperCase());
}

function actorLabel(actor: AuditActor): string {
	const name = actor.name?.trim();
	const email = actor.email?.trim();
	if (name && email) return `${name} (${email})`;
	return name || email || "Unknown user";
}

function eventActionLabel(command: string): string {
	return humanize(command.split(".").at(-1) ?? command);
}

function indicatorClass(command: string, eventKind: AuditEventListItem["event_kind"]): string {
	if (eventKind === "access") return "bg-sky-500";
	if (command.includes("reject") || command.includes("reverse")) return "bg-rose-500";
	if (command.includes("submit") || command.includes("post")) return "bg-amber-500";
	return "bg-primary";
}

function SelectFilter({
	label,
	value,
	options,
	onChange,
}: {
	label: string;
	value: string | null;
	options: { value: string; label: string }[];
	onChange: (value: string | null) => void;
}) {
	const selectedOption = options.find((option) => option.value === value) ?? null;
	return (
		<Combobox
			items={options}
			value={selectedOption}
			onValueChange={(nextValue) => onChange(nextValue?.value ?? null)}
			itemToStringLabel={(item) => item.label}
			itemToStringValue={(item) => item.label}
		>
			<ComboboxInput
				placeholder={label}
				aria-label={`Filter by ${label}`}
				showClear
				className="w-48 shrink-0"
			/>
			<ComboboxContent>
				<ComboboxEmpty>No options found.</ComboboxEmpty>
				<ComboboxList>
					{(option: { value: string; label: string }) => (
						<ComboboxItem key={option.value} value={option}>
							{option.label}
						</ComboboxItem>
					)}
				</ComboboxList>
			</ComboboxContent>
		</Combobox>
	);
}

function AuditWorkspaceSkeleton() {
	return (
		<div className="grid min-h-[32rem] grid-cols-1 lg:grid-cols-[340px_minmax(0,1fr)]">
			<div className="grid content-start gap-3 border-r border-border p-4">
				<Skeleton className="h-4 w-28" />
				{["one", "two", "three", "four", "five", "six"].map((key) => (
					<Skeleton key={key} className="h-14 w-full" />
				))}
			</div>
			<div className="hidden content-start gap-5 p-6 lg:grid">
				<Skeleton className="h-4 w-48" />
				<Skeleton className="h-4 w-36" />
				<Skeleton className="h-56 w-full" />
			</div>
		</div>
	);
}

export default function AuditPage() {
	const isDesktop = useDesktopLayout();
	const [entityType, setEntityType] = useState<string | null>(null);
	const [actorId, setActorId] = useState<string | null>(null);
	const [command, setCommand] = useState<string | null>(null);
	const [entityId, setEntityId] = useState("");
	const [dateRange, setDateRange] = useState<DateRange | undefined>();
	const [page, setPage] = useState(1);
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [sheetOpen, setSheetOpen] = useState(false);
	const debouncedEntityId = useDebouncedValue(entityId, 300);
	const optionsQuery = useAuditFilterOptions();

	const listParams = useMemo(
		() => ({
			entity_type: entityType,
			actor_user_id: actorId,
			command,
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
		[entityType, actorId, command, debouncedEntityId, dateRange, page],
	);
	const listQuery = useAuditEventsList(listParams);
	const events = listQuery.data?.items ?? [];
	const totalPages = listQuery.data?.total_pages ?? 1;
	const hasFilters = Boolean(entityType || actorId || command || entityId || dateRange?.from);
	const entityTypeOptions = useMemo(
		() =>
			(optionsQuery.data?.entity_types ?? []).map((value) => ({
				value,
				label: humanize(value),
			})),
		[optionsQuery.data?.entity_types],
	);
	const actorOptions = useMemo(
		() =>
			(optionsQuery.data?.actors ?? []).map((actor) => ({
				value: actor.id,
				label: actorLabel(actor),
			})),
		[optionsQuery.data?.actors],
	);
	const commandOptions = useMemo(
		() =>
			(optionsQuery.data?.commands ?? []).map((value) => ({
				value,
				label: eventActionLabel(value),
			})),
		[optionsQuery.data?.commands],
	);

	useEffect(() => {
		if (listQuery.isLoading || listQuery.isError) return;
		if (events.length === 0) {
			setSelectedId(null);
			setSheetOpen(false);
			return;
		}
		if (!events.some((event) => event.id === selectedId)) {
			setSelectedId(isDesktop ? events[0].id : null);
			setSheetOpen(false);
		}
	}, [events, isDesktop, listQuery.isError, listQuery.isLoading, selectedId]);

	const groups = useMemo(() => {
		const grouped = new Map<string, AuditEventListItem[]>();
		for (const event of events) {
			const day = formatDateInAccordTimeZone(event.created_at);
			grouped.set(day, [...(grouped.get(day) ?? []), event]);
		}
		return Array.from(grouped.entries());
	}, [events]);

	const selectedEvent = events.find((event) => event.id === selectedId) ?? null;
	const changeFilter = (setter: (value: string | null) => void) => (value: string | null) => {
		setter(value);
		setPage(1);
	};
	const resetFilters = () => {
		setEntityType(null);
		setActorId(null);
		setCommand(null);
		setEntityId("");
		setDateRange(undefined);
		setPage(1);
	};

	return (
		<CapabilityGate capability="view_audit" title="Audit">
			<AppLayout title="Audit">
				<PageShell data-testid="audit-page">
					<div className="flex min-h-0 flex-1 flex-col gap-3">
						<div
							className="app-scrollbar flex shrink-0 items-center gap-2 overflow-x-auto pb-1"
							data-testid="audit-filter-toolbar"
						>
							<SelectFilter
								label="Entity Type"
								value={entityType}
								onChange={changeFilter(setEntityType)}
								options={entityTypeOptions}
							/>
							<Input
								value={entityId}
								onChange={(event) => {
									setEntityId(event.target.value);
									setPage(1);
								}}
								placeholder="Entity ID"
								aria-label="Filter by Entity ID"
								className="w-48 shrink-0"
							/>
							<SelectFilter
								label="Actor"
								value={actorId}
								onChange={changeFilter(setActorId)}
								options={actorOptions}
							/>
							<SelectFilter
								label="Action"
								value={command}
								onChange={changeFilter(setCommand)}
								options={commandOptions}
							/>
							<DateRangePicker
								value={dateRange}
								onValueChange={(range) => {
									setDateRange(range);
									setPage(1);
								}}
								aria-label="Filter by Date Range"
								placeholder="Dates"
								numberOfMonths={isDesktop ? 2 : 1}
								className="w-56 shrink-0"
							/>
							{hasFilters ? (
								<Button variant="ghost" onClick={resetFilters} className="shrink-0">
									Reset
								</Button>
							) : null}
						</div>

						<div
							className="app-material-level-1 flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border bg-card isolate"
							data-testid="audit-workspace"
						>
							{listQuery.isLoading ? <AuditWorkspaceSkeleton /> : null}
							{listQuery.isError ? (
								<div className="p-6">
									<ErrorWithRetry
										message={getErrorMessage(listQuery.error, "Failed to load audit events.")}
										onRetry={() => void listQuery.refetch()}
									/>
								</div>
							) : null}
							{!listQuery.isLoading && !listQuery.isError && events.length === 0 ? (
								<EmptyState
									icon={ClipboardList}
									title="No audit events"
									description="No events match the current filters."
									className="min-h-[32rem] flex-1"
								/>
							) : null}
							{!listQuery.isLoading && !listQuery.isError && events.length > 0 ? (
								<div className="grid min-h-0 flex-1 overflow-hidden rounded-[inherit] lg:grid-cols-[340px_minmax(0,1fr)]">
									<section className="grid min-h-0 grid-rows-[minmax(0,1fr)_auto] overflow-hidden border-border lg:border-r">
										<div
											className={cn(
												"app-scrollbar min-h-0 overflow-y-auto",
												listQuery.isPlaceholderData && "pointer-events-none opacity-70",
											)}
											aria-busy={listQuery.isPlaceholderData || undefined}
										>
											{groups.map(([day, dayEvents], groupIndex) => (
												<div key={day}>
													<div
														className={cn(
															"sticky top-0 z-10 border-b border-border bg-muted/95 px-4 py-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase",
															groupIndex === 0 && "rounded-t-lg lg:rounded-tr-none",
														)}
													>
														{day}
													</div>
													{dayEvents.map((event) => (
														<button
															type="button"
															key={event.id}
															disabled={listQuery.isPlaceholderData}
															aria-current={event.id === selectedId ? "true" : undefined}
															className={cn(
																"grid w-full grid-cols-[auto_minmax(0,1fr)] gap-3 border-b border-border px-4 py-3 text-left transition-colors hover:bg-accent/45",
																event.id === selectedId && "bg-accent/60",
																listQuery.isPlaceholderData && "cursor-wait",
															)}
															onClick={() => {
																setSelectedId(event.id);
																if (!isDesktop) setSheetOpen(true);
															}}
														>
															<span
																className={cn(
																	"mt-1.5 size-2 rounded-full",
																	indicatorClass(event.command, event.event_kind),
																)}
															/>
															<span className="min-w-0">
																<span className="block truncate text-sm font-medium">
																	{event.entity_label}
																</span>
																<span className="mt-1 flex items-center justify-between gap-3 text-xs text-muted-foreground">
																	<span>{eventActionLabel(event.command)}</span>
																	<span>{formatDateTime(event.created_at).split(", ").at(-1)}</span>
																</span>
															</span>
														</button>
													))}
												</div>
											))}
										</div>
										<div className="rounded-b-lg border-t border-border p-2 lg:rounded-br-none">
											<PaginationControls
												page={page}
												totalPages={totalPages}
												onPageChange={setPage}
												compact
												disabled={listQuery.isPlaceholderData}
											/>
										</div>
									</section>
									{selectedId ? (
										<main
											className="app-scrollbar hidden min-h-0 overflow-y-auto rounded-r-lg p-6 lg:block"
											data-testid="audit-detail-panel"
										>
											<AuditEventDetail eventId={selectedId} />
										</main>
									) : null}
								</div>
							) : null}
						</div>
					</div>
				</PageShell>

				<Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
					<SheetContent side="right" className="w-full sm:max-w-lg">
						<SheetHeader>
							<SheetTitle>{selectedEvent?.entity_label ?? "Audit event"}</SheetTitle>
							<SheetDescription>
								{selectedEvent ? eventActionLabel(selectedEvent.command) : "Event details"}
							</SheetDescription>
						</SheetHeader>
						{selectedId ? (
							<div className="app-scrollbar min-h-0 flex-1 overflow-y-auto px-4 pb-4">
								<AuditEventDetail eventId={selectedId} />
							</div>
						) : null}
					</SheetContent>
				</Sheet>
			</AppLayout>
		</CapabilityGate>
	);
}
