import { ClipboardTextIcon as ClipboardList } from "@phosphor-icons/react/dist/csr/ClipboardText";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { DateRange } from "react-day-picker";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { EmptyState } from "@/components/empty-state";
import { PageShell } from "@/components/page-shell";
import { PaginationControls } from "@/components/pagination-controls";
import { Badge } from "@/components/ui/badge";
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
import {
	Drawer,
	DrawerClose,
	DrawerContent,
	DrawerDescription,
	DrawerHeader,
	DrawerTitle,
} from "@/components/ui/drawer";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
	type AuditActor,
	type AuditEventListItem,
	toAuditDayBound,
	useAuditEventsList,
	useAuditFilterOptions,
} from "@/lib/api/audit";
import { getErrorMessage } from "@/lib/errors";
import {
	ACCORD_TIME_ZONE,
	cn,
	formatDateInAccordTimeZone,
	parseApiDateTime,
} from "@/lib/utils";

import { AuditEventDetail } from "./AuditEventDetail";
import { commandBadgeVariant } from "./CommandBadge";

const PAGE_SIZE = 20;
const DESKTOP_QUERY = "(min-width: 1024px)";

const eventTimeFormatter = new Intl.DateTimeFormat("en-IN", {
	timeZone: ACCORD_TIME_ZONE,
	hour: "numeric",
	minute: "2-digit",
	hour12: true,
});

function formatEventTime(value: string): string {
	const date = parseApiDateTime(value);
	return date ? eventTimeFormatter.format(date) : "—";
}

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
		.split(/\s+/)
		.filter(Boolean)
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
		.join(" ");
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

/** Strip trailing short entity-id suffixes from fallback labels (e.g. "Payroll Run fc4f9737"). */
function eventEntityLabel(event: AuditEventListItem): string {
	const shortId = event.entity_id.slice(0, 8);
	const label = event.entity_label.trim();
	if (label.endsWith(shortId)) {
		const withoutId = label.slice(0, -shortId.length).trim();
		return withoutId || humanize(event.entity_type);
	}
	return label;
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
		<div className="grid min-h-[32rem] grid-cols-1 gap-2 p-2 lg:grid-cols-[340px_minmax(0,1fr)]">
			<div className="grid content-start gap-3 rounded-lg border border-border bg-muted/20 p-4">
				<Skeleton className="h-4 w-28" />
				{["one", "two", "three", "four", "five", "six"].map((key) => (
					<Skeleton key={key} className="h-14 w-full rounded-md" />
				))}
			</div>
			<div className="hidden content-start gap-5 rounded-lg p-3 lg:grid">
				<Skeleton className="h-4 w-48" />
				<Skeleton className="h-4 w-36" />
				<Skeleton className="h-56 w-full rounded-md" />
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
	const [drawerOpen, setDrawerOpen] = useState(false);
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
			setDrawerOpen(false);
			return;
		}
		if (!events.some((event) => event.id === selectedId)) {
			setSelectedId(isDesktop ? events[0].id : null);
			setDrawerOpen(false);
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
							className="app-table-surface flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-card"
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
									title="No Audit Events"
									description="No events match the current filters."
									className="min-h-[32rem] flex-1"
								/>
							) : null}
							{!listQuery.isLoading && !listQuery.isError && events.length > 0 ? (
								<div className="grid min-h-0 flex-1 gap-2 overflow-hidden p-2 lg:grid-cols-[340px_minmax(0,1fr)]">
									<section className="grid min-h-0 grid-rows-[minmax(0,1fr)_auto] overflow-hidden rounded-lg border border-border bg-muted/20">
										<div
											className={cn(
												"app-scrollbar min-h-0 overflow-y-auto",
												listQuery.isPlaceholderData && "pointer-events-none opacity-70",
											)}
											aria-busy={listQuery.isPlaceholderData || undefined}
										>
											{groups.map(([day, dayEvents]) => (
												<div key={day}>
													<div className="sticky top-0 z-10 border-b border-border bg-muted/95 px-4 py-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
														{day}
													</div>
													{dayEvents.map((event) => (
														<button
															type="button"
															key={event.id}
															disabled={listQuery.isPlaceholderData}
															aria-current={event.id === selectedId ? "true" : undefined}
															className={cn(
																"flex w-full items-center gap-3 border-b border-border px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-accent/45",
																event.id === selectedId && "bg-accent/60",
																listQuery.isPlaceholderData && "cursor-wait",
															)}
															onClick={() => {
																setSelectedId(event.id);
																if (!isDesktop) setDrawerOpen(true);
															}}
														>
															<span
																className={cn(
																	"size-2 shrink-0 rounded-full",
																	indicatorClass(event.command, event.event_kind),
																)}
															/>
															<span className="flex min-w-0 flex-1 items-center gap-3">
																<span className="min-w-0 flex-1 truncate text-sm font-medium">
																	{eventEntityLabel(event)}
																</span>
																<span className="flex shrink-0 items-center gap-2">
																	<Badge variant={commandBadgeVariant(event.command)}>
																		{eventActionLabel(event.command)}
																	</Badge>
																	<span className="text-xs text-muted-foreground tabular-nums">
																		{formatEventTime(event.created_at)}
																	</span>
																</span>
															</span>
														</button>
													))}
												</div>
											))}
										</div>
										<div className="rounded-b-lg border-t border-border bg-muted/30 p-2">
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
											className="app-scrollbar hidden min-h-0 overflow-y-auto rounded-lg p-3 lg:block"
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

				<Drawer open={drawerOpen} onOpenChange={setDrawerOpen} swipeDirection="right">
					<DrawerContent className="sm:[--drawer-content-width:32rem]">
						<DrawerHeader className="relative pr-12">
							<DrawerTitle>
								{selectedEvent ? eventEntityLabel(selectedEvent) : "Audit event"}
							</DrawerTitle>
							<DrawerDescription className="sr-only">
								{selectedEvent ? eventActionLabel(selectedEvent.command) : "Event details"}
							</DrawerDescription>
							{selectedEvent ? (
								<Badge variant={commandBadgeVariant(selectedEvent.command)} className="w-fit">
									{eventActionLabel(selectedEvent.command)}
								</Badge>
							) : null}
							<DrawerClose
								render={
									<Button
										variant="ghost"
										size="icon"
										aria-label="Close"
										className="absolute top-3 right-3"
									/>
								}
							>
								<XIcon weight="bold" aria-hidden />
							</DrawerClose>
						</DrawerHeader>
						{selectedId ? (
							<div className="app-scrollbar min-h-0 flex-1 overflow-y-auto p-4">
								<AuditEventDetail eventId={selectedId} />
							</div>
						) : null}
					</DrawerContent>
				</Drawer>
			</AppLayout>
		</CapabilityGate>
	);
}
