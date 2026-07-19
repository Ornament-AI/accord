import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "@/lib/api/http";
import { shouldSetQueryParam } from "@/lib/api/query-utils";
import type { components } from "@/types/api.generated";

export type AuditActor = components["schemas"]["AuditActor"];
export type AuditEventListItem = components["schemas"]["AuditEventListItem"];
export type AuditEventDetail = components["schemas"]["AuditEventDetailResponse"];
/** @deprecated Use the compact list item or structured detail type explicitly. */
export type AuditEventResponse = AuditEventListItem;
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

function buildQueryString(
	params: Record<string, string | number | boolean | null | undefined>,
): string {
	const search = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (!shouldSetQueryParam(key, value)) continue;
		search.set(key, String(value));
	}
	const qs = search.toString();
	return qs ? `?${qs}` : "";
}

export function toAuditDayBound(date: Date, bound: "start" | "end"): string {
	const year = date.getFullYear();
	const month = String(date.getMonth() + 1).padStart(2, "0");
	const day = String(date.getDate()).padStart(2, "0");
	return bound === "start"
		? `${year}-${month}-${day}T00:00:00`
		: `${year}-${month}-${day}T23:59:59`;
}

export function listAuditEvents(params: ListAuditEventsParams = {}) {
	const qs = buildQueryString(params);
	return fetchJson<PaginatedAuditEventResponse>(`/api/audit-events${qs}`);
}

export function getAuditEvent(eventId: string) {
	return fetchJson<AuditEventDetail>(`/api/audit-events/${eventId}`);
}

export function getAuditFilterOptions() {
	return fetchJson<AuditFilterOptions>("/api/audit-events/filter-options");
}

export function useAuditEventsList(params: ListAuditEventsParams) {
	return useQuery({
		queryKey: auditQueryKeys.list(params),
		queryFn: () => listAuditEvents(params),
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
