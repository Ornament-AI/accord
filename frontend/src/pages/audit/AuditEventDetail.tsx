import { ChevronDown, ClipboardList } from "lucide-react";
import { type ReactNode, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Skeleton } from "@/components/ui/skeleton";
import { type AuditEventResponse, useAuditEvent } from "@/lib/api/audit";
import { getErrorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/utils";

import { CommandBadge } from "./CommandBadge";

function FieldRow({ label, value }: { label: string; value: ReactNode }) {
	return (
		<div className="grid grid-cols-[8rem_1fr] gap-2 text-sm">
			<dt className="text-muted-foreground">{label}</dt>
			<dd className="min-w-0 break-words text-foreground">{value ?? "—"}</dd>
		</div>
	);
}

function isFlatSummaryValue(value: unknown): value is string | number | boolean | null {
	return (
		value === null ||
		typeof value === "string" ||
		typeof value === "number" ||
		typeof value === "boolean"
	);
}

function formatSummaryValue(value: unknown): string {
	if (value === null) return "null";
	if (typeof value === "string") return value;
	if (typeof value === "number" || typeof value === "boolean") return String(value);
	try {
		return JSON.stringify(value);
	} catch {
		return String(value);
	}
}

function actorDisplay(event: AuditEventResponse): string {
	if (!event.actor) return "System";
	const name = event.actor.name?.trim();
	const email = event.actor.email?.trim();
	if (name && email) return `${name} (${email})`;
	return name || email || "System";
}

function SummarySection({ summary }: { summary: AuditEventResponse["summary"] }) {
	const [rawOpen, setRawOpen] = useState(false);
	const entries = Object.entries(summary ?? {});
	const flatEntries = entries.filter(([, value]) => isFlatSummaryValue(value));
	const rawJson = JSON.stringify(summary ?? {}, null, 2);

	return (
		<div className="grid gap-3" data-testid="audit-event-summary">
			{flatEntries.length > 0 ? (
				<dl className="grid gap-2">
					{flatEntries.map(([key, value]) => (
						<FieldRow key={key} label={key} value={formatSummaryValue(value)} />
					))}
				</dl>
			) : (
				<p className="text-sm text-muted-foreground">No flat summary fields.</p>
			)}

			<Collapsible open={rawOpen} onOpenChange={setRawOpen}>
				<CollapsibleTrigger
					render={
						<Button type="button" variant="ghost" className="h-8 w-full justify-between px-2" />
					}
				>
					<span>Raw JSON</span>
					<ChevronDown className="size-4 opacity-60" />
				</CollapsibleTrigger>
				<CollapsibleContent className="pt-2">
					<pre
						className="max-h-64 overflow-auto rounded-md bg-muted/40 p-3 text-xs whitespace-pre-wrap"
						data-testid="audit-event-summary-raw"
					>
						{rawJson}
					</pre>
				</CollapsibleContent>
			</Collapsible>
		</div>
	);
}

function AuditEventDetailBody({ event }: { event: AuditEventResponse }) {
	return (
		<div className="grid gap-4" data-testid="audit-event-detail">
			<dl className="grid gap-3">
				<FieldRow label="Actor" value={actorDisplay(event)} />
				<FieldRow label="Command" value={<CommandBadge command={event.command} />} />
				<FieldRow label="Entity" value={`${event.entity_type} · ${event.entity_id}`} />
				<FieldRow label="Request ID" value={event.request_id ?? "—"} />
				<FieldRow label="Created" value={formatDateTime(event.created_at)} />
			</dl>

			<div className="grid gap-2">
				<h3 className="text-sm font-medium">Summary</h3>
				<SummarySection summary={event.summary} />
			</div>
		</div>
	);
}

export function AuditEventDetail({ eventId }: { eventId: string | null }) {
	const detailQuery = useAuditEvent(eventId ?? undefined);

	if (!eventId) {
		return (
			<EmptyState
				icon={ClipboardList}
				title="Select an event"
				description="Choose an audit event from the list to inspect its details."
			/>
		);
	}

	if (detailQuery.isLoading) {
		return (
			<div className="grid gap-3" data-testid="audit-event-detail-loading">
				<Skeleton className="h-4 w-40" />
				<Skeleton className="h-4 w-56" />
				<Skeleton className="h-4 w-48" />
				<Skeleton className="h-24 w-full" />
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

	if (!detailQuery.data) {
		return (
			<EmptyState
				icon={ClipboardList}
				title="Event not found"
				description="This audit event could not be loaded."
			/>
		);
	}

	return <AuditEventDetailBody event={detailQuery.data} />;
}
