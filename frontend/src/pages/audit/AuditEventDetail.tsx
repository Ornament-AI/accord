import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Skeleton } from "@/components/ui/skeleton";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { type AuditEventDetail as AuditEventDetailData, useAuditEvent } from "@/lib/api/audit";
import { getErrorMessage } from "@/lib/errors";
import { ACCORD_TIME_ZONE, formatDateInAccordTimeZone, parseApiDateTime } from "@/lib/utils";

const HIDDEN_DIFF_FIELDS = new Set([
	"organization_id",
	"created_at",
	"updated_at",
	"lock_version",
	"version",
]);

const timeFormatter = new Intl.DateTimeFormat("en-IN", {
	timeZone: ACCORD_TIME_ZONE,
	hour: "numeric",
	minute: "2-digit",
	hour12: true,
});

function humanize(value: string): string {
	return value
		.replaceAll("_", " ")
		.replace(/([a-z])([A-Z])/g, "$1 $2")
		.replace(/^./, (character) => character.toUpperCase());
}

function displayValue(value: unknown): string {
	if (value === null || value === undefined || value === "") return "—";
	if (typeof value === "boolean") return value ? "Yes" : "No";
	if (typeof value === "string" || typeof value === "number") return String(value);
	if (Array.isArray(value)) return value.map(displayValue).join(", ") || "—";
	return "Structured value";
}

function actorDisplay(event: AuditEventDetailData): string {
	if (!event.actor) return "System";
	const name = event.actor.name?.trim();
	const email = event.actor.email?.trim();
	if (name && email) return `${name} (${email})`;
	return name || email || "System";
}

function EventMetadata({ event }: { event: AuditEventDetailData }) {
	const date = parseApiDateTime(event.created_at);
	return (
		<dl className="grid grid-cols-[5rem_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
			<dt className="text-muted-foreground">Actor</dt>
			<dd>{actorDisplay(event)}</dd>
			<dt className="text-muted-foreground">Entity</dt>
			<dd>{humanize(event.entity_type)}</dd>
			<dt className="text-muted-foreground">Entity ID</dt>
			<dd className="min-w-0 break-all font-mono text-xs">{event.entity_id}</dd>
			<dt className="text-muted-foreground">Date</dt>
			<dd>{formatDateInAccordTimeZone(event.created_at)}</dd>
			<dt className="text-muted-foreground">Time</dt>
			<dd>{date ? timeFormatter.format(date) : "—"}</dd>
			{event.request_id ? (
				<>
					<dt className="text-muted-foreground">Request</dt>
					<dd className="min-w-0 break-all font-mono text-xs">{event.request_id}</dd>
				</>
			) : null}
		</dl>
	);
}

function MutationDetail({ event }: { event: AuditEventDetailData }) {
	const before = event.before_state ?? {};
	const after = event.after_state ?? {};
	const changedFields = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]))
		.filter((key) => !HIDDEN_DIFF_FIELDS.has(key) && before[key] !== after[key])
		.sort((left, right) => left.localeCompare(right));
	const context = event.access_details ?? {};
	const hasContext = Object.keys(context).length > 0;

	return (
		<div className="grid gap-5">
			{hasContext ? (
				<section className="grid gap-3">
					<h3 className="text-sm font-semibold">Context</h3>
					<KeyValueDetails values={context} />
				</section>
			) : null}
			<section className="grid gap-3">
				<h3 className="text-sm font-semibold">Changes</h3>
				<Table containerClassName="shadow-none">
					<TableHeader>
						<TableRow className="hover:bg-transparent dark:hover:bg-transparent">
							<TableHead>Field</TableHead>
							<TableHead>Before</TableHead>
							<TableHead>After</TableHead>
						</TableRow>
					</TableHeader>
					<TableBody>
						{changedFields.map((field) => (
							<TableRow key={field}>
								<TableCell className="font-medium">{humanize(field)}</TableCell>
								<TableCell className="max-w-64 whitespace-normal text-muted-foreground">
									{displayValue(before[field])}
								</TableCell>
								<TableCell className="max-w-64 whitespace-normal">
									{displayValue(after[field])}
								</TableCell>
							</TableRow>
						))}
					</TableBody>
				</Table>
			</section>
		</div>
	);
}

function KeyValueDetails({ values }: { values: Record<string, unknown> }) {
	const entries = Object.entries(values).filter(
		([key]) => !HIDDEN_DIFF_FIELDS.has(key) && key !== "object_key",
	);
	return (
		<dl className="grid grid-cols-[9rem_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
			{entries.map(([key, value]) => (
				<div key={key} className="contents">
					<dt className="text-muted-foreground">{humanize(key)}</dt>
					<dd className="min-w-0 break-words">{displayValue(value)}</dd>
				</div>
			))}
		</dl>
	);
}

function AccessDetail({ event }: { event: AuditEventDetailData }) {
	return (
		<div className="grid gap-5">
			<section className="grid gap-2">
				<h3 className="text-sm font-semibold">Resource</h3>
				<p className="text-sm">{event.entity_label}</p>
			</section>
			<section className="grid gap-3">
				<h3 className="text-sm font-semibold">Access Details</h3>
				<KeyValueDetails
					values={{ ...(event.resource_state ?? {}), ...(event.access_details ?? {}) }}
				/>
			</section>
		</div>
	);
}

function AuditEventDetailBody({ event }: { event: AuditEventDetailData }) {
	return (
		<div className="grid gap-6" data-testid="audit-event-detail">
			<EventMetadata event={event} />
			{!event.has_structured_detail ? (
				<p className="rounded-md border border-border bg-muted/20 p-4 text-sm text-muted-foreground">
					Detailed changes were not recorded for this legacy event.
				</p>
			) : event.event_kind === "access" ? (
				<AccessDetail event={event} />
			) : (
				<MutationDetail event={event} />
			)}
		</div>
	);
}

export function AuditEventDetail({ eventId }: { eventId: string }) {
	const detailQuery = useAuditEvent(eventId);

	if (detailQuery.isLoading) {
		return (
			<div className="grid gap-4" data-testid="audit-event-detail-loading">
				<div className="grid grid-cols-[5rem_1fr] gap-3">
					<Skeleton className="h-4 w-12" />
					<Skeleton className="h-4 w-40" />
					<Skeleton className="h-4 w-12" />
					<Skeleton className="h-4 w-28" />
				</div>
				<Skeleton className="h-48 w-full" />
			</div>
		);
	}

	if (detailQuery.isError) {
		return (
			<ErrorWithRetry
				message={getErrorMessage(detailQuery.error, "Failed to load audit event.")}
				onRetry={() => void detailQuery.refetch()}
			/>
		);
	}

	return detailQuery.data ? <AuditEventDetailBody event={detailQuery.data} /> : null;
}
