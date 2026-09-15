import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "@/lib/api/http";
import { buildQueryString, shouldSetQueryParam } from "@/lib/api/query-utils";
import { ACCORD_TIME_ZONE } from "@/lib/utils";
import type { components } from "@/types/api.generated";

export type AuditActor = components["schemas"]["AuditActor"];
export type AuditEventListItem = components["schemas"]["AuditEventListItem"];
export type AuditEventDetail = components["schemas"]["AuditEventDetailResponse"];
export type AuditFilterOptions = components["schemas"]["AuditFilterOptionsResponse"];
export type PaginatedAuditEventResponse =
	components["schemas"]["PaginatedResponse_AuditEventListItem_"];

export type ListAuditEventsParams = {
	entity_type?: string | null;
	entity_id?: string | null;
	command?: string | null;
	actor_user_id?: string | null;
	from?: string | null;
	to?: string | null;
	page?: number;
	page_size?: number;
};

export const auditQueryKeys = {
	all: () => ["audit-events"] as const,
	list: (params: ListAuditEventsParams) => ["audit-events", "list", params] as const,
	detail: (eventId: string) => ["audit-events", "detail", eventId] as const,
	filterOptions: () => ["audit-events", "filter-options"] as const,
};

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The audit `entity_id` filter is a backend UUID — gate partial input before querying. */
export function isUuid(value: string): boolean {
	return UUID_PATTERN.test(value.trim());
}

const accordOffsetFormatter = new Intl.DateTimeFormat("en-US", {
	timeZone: ACCORD_TIME_ZONE,
	timeZoneName: "longOffset",
});

/** UTC offset (e.g. "+05:30") of ACCORD_TIME_ZONE at the given instant. */
function accordTimeZoneOffset(date: Date): string {
	const name = accordOffsetFormatter
		.formatToParts(date)
		.find((part) => part.type === "timeZoneName")?.value;
	if (!name || name === "GMT" || name === "UTC") return "+00:00";
	return name.replace(/^(?:GMT|UTC)/, "");
}

/**
 * Calendar-day bounds in ACCORD_TIME_ZONE, sent offset-aware: the backend
 * normalizes aware instants to UTC, so a naive "00:00:00" would be read as a
 * UTC midnight and skew the IST day the audit UI groups by.
 */
export function toAuditDayBound(date: Date, bound: "start" | "end"): string {
	const year = date.getFullYear();
	const month = String(date.getMonth() + 1).padStart(2, "0");
	const day = String(date.getDate()).padStart(2, "0");
	const offset = accordTimeZoneOffset(date);
	return bound === "start"
		? `${year}-${month}-${day}T00:00:00${offset}`
		: `${year}-${month}-${day}T23:59:59.999999${offset}`;
}

export function listAuditEvents(params: ListAuditEventsParams = {}) {
	const qs = buildQueryString(params, shouldSetQueryParam);
	return fetchJson<PaginatedAuditEventResponse>(`/api/audit-events${qs}`);
}

export function getAuditEvent(eventId: string) {
	return fetchJson<AuditEventDetail>(`/api/audit-events/${eventId}`);
}

export function getAuditFilterOptions() {
	return fetchJson<AuditFilterOptions>("/api/audit-events/filter-options");
}

export function useAuditEventsList(params: ListAuditEventsParams, enabled = true) {
	return useQuery({
		queryKey: auditQueryKeys.list(params),
		queryFn: () => listAuditEvents(params),
		enabled,
		placeholderData: (previous) => previous,
	});
}

export function useAuditEvent(eventId: string | undefined) {
	return useQuery({
		queryKey: auditQueryKeys.detail(eventId ?? ""),
		queryFn: () => getAuditEvent(eventId!),
		enabled: Boolean(eventId),
	});
}

export function useAuditFilterOptions() {
	return useQuery({
		queryKey: auditQueryKeys.filterOptions(),
		queryFn: getAuditFilterOptions,
		staleTime: 60_000,
	});
}
