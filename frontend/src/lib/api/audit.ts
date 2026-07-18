import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "@/lib/api/http";
import { shouldSetQueryParam } from "@/lib/api/query-utils";
import type { components } from "@/types/api.generated";

export type AuditActor = components["schemas"]["AuditActor"];
export type AuditEventResponse = components["schemas"]["AuditEventResponse"];
export type PaginatedAuditEventResponse =
	components["schemas"]["PaginatedResponse_AuditEventResponse_"];

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

/** Format a local Date as an inclusive day-bound API datetime (naive). */
export function toAuditDayBound(date: Date, bound: "start" | "end"): string {
	const year = date.getFullYear();
	const month = String(date.getMonth() + 1).padStart(2, "0");
	const day = String(date.getDate()).padStart(2, "0");
	return bound === "start"
		? `${year}-${month}-${day}T00:00:00`
		: `${year}-${month}-${day}T23:59:59`;
}

export function listAuditEvents(params: ListAuditEventsParams = {}) {
	const qs = buildQueryString({
		entity_type: params.entity_type,
		entity_id: params.entity_id,
		command: params.command,
		actor_user_id: params.actor_user_id,
		from: params.from,
		to: params.to,
		page: params.page,
		page_size: params.page_size,
	});
	return fetchJson<PaginatedAuditEventResponse>(`/api/audit-events${qs}`);
}

export function getAuditEvent(eventId: string) {
	return fetchJson<AuditEventResponse>(`/api/audit-events/${eventId}`);
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
