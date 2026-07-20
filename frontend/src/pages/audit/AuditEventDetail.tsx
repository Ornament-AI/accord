import { FieldsValueTable } from "@/components/fields-value-table";
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
		.split(/\s+/)
		.filter(Boolean)
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
		.join(" ");
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
	return event.actor.email?.trim() || event.actor.name?.trim() || "System";
}

function EventMetadata({ event }: { event: AuditEventDetailData }) {
	const date = parseApiDateTime(event.created_at);
	const rows = [
		{ label: "Actor", value: actorDisplay(event) },
		{ label: "Entity", value: humanize(event.entity_type) },
		{
			label: "Entity ID",
			value: <span className="break-all font-mono">{event.entity_id}</span>,
		},
		{ label: "Date", value: formatDateInAccordTimeZone(event.created_at) },
		{ label: "Time", value: date ? timeFormatter.format(date) : "—" },
		...(event.request_id
			? [
					{
						label: "Request",
						value: <span className="break-all font-mono">{event.request_id}</span>,
					},
				]
			: []),
	];
	return <FieldsValueTable rows={rows} />;
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
	const rows = Object.entries(values)
		.filter(([key]) => !HIDDEN_DIFF_FIELDS.has(key) && key !== "object_key")
		.map(([key, value]) => ({
			label: humanize(key),
			value: <span className="break-words">{displayValue(value)}</span>,
		}));
	return <FieldsValueTable rows={rows} />;
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
			{event.event_kind === "access" ? (
				<AccessDetail event={event} />
			) : event.event_kind === "mutation" ? (
				<MutationDetail event={event} />
			) : null}
		</div>
	);
}

export function AuditEventDetail({ eventId }: { eventId: string }) {
	const detailQuery = useAuditEvent(eventId);

	if (detailQuery.isLoading) {
		return (
			<div className="grid gap-4" data-testid="audit-event-detail-loading">
				<Skeleton className="h-40 w-full" />
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
