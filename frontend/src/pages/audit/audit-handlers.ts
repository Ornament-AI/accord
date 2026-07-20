import { HttpResponse, http } from "msw";

import type {
	AuditEventDetail,
	AuditEventListItem,
	AuditFilterOptions,
	PaginatedAuditEventResponse,
} from "@/lib/api/audit";

export type AuditHandlersOptions = {
	events?: AuditEventDetail[];
	pageSize?: number;
	empty?: boolean;
};

export type CapturedAuditListRequest = {
	entity_type: string | null;
	entity_id: string | null;
	command: string | null;
	actor_user_id: string | null;
	from: string | null;
	to: string | null;
	page: string | null;
	page_size: string | null;
};

function listItem(event: AuditEventDetail): AuditEventListItem {
	const {
		request_id: _requestId,
		before_state: _beforeState,
		after_state: _afterState,
		resource_state: _resourceState,
		access_details: _accessDetails,
		...item
	} = event;
	return item;
}

export function buildAuditEvent(
	overrides: Partial<AuditEventDetail> & { id: string },
): AuditEventDetail {
	const command = overrides.command ?? "submit";
	const beforeState = overrides.before_state ?? { status: "calculated", lock_version: 1 };
	const afterState = overrides.after_state ?? { status: "submitted", lock_version: 2 };
	return {
		id: overrides.id,
		command,
		event_kind: overrides.event_kind ?? "mutation",
		entity_type: overrides.entity_type ?? "payroll_run",
		entity_id: overrides.entity_id ?? "11111111-1111-1111-1111-111111111111",
		entity_label: overrides.entity_label ?? "2026-07 payroll run",
		actor:
			overrides.actor === undefined
				? {
						id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
						name: "Ada Lovelace",
						email: "ada@example.com",
					}
				: overrides.actor,
		changed_count: overrides.changed_count ?? 1,
		request_id: overrides.request_id ?? "req-001",
		before_state: beforeState,
		after_state: afterState,
		resource_state: overrides.resource_state ?? null,
		access_details: overrides.access_details ?? {},
		created_at: overrides.created_at ?? "2026-07-18T10:00:00",
	};
}

function defaultEvents(count: number): AuditEventDetail[] {
	return Array.from({ length: count }, (_, index) => {
		const n = index + 1;
		const created = new Date(Date.UTC(2026, 6, 18, 12, 0, 0));
		created.setUTCMinutes(created.getUTCMinutes() - index);
		const command =
			index % 4 === 0
				? "payroll_run.post"
				: index % 4 === 1
					? "artifact.download"
					: index % 4 === 2
						? "approve"
						: "submit";
		const isAccess = command === "artifact.download";
		return buildAuditEvent({
			id: `aaaaaaaa-bbbb-cccc-dddd-${String(n).padStart(12, "0")}`,
			command,
			event_kind: isAccess ? "access" : "mutation",
			entity_type: isAccess ? "export_artifact" : "payroll_run",
			entity_id: `22222222-2222-2222-2222-${String(n).padStart(12, "0")}`,
			entity_label: isAccess ? `Payroll Register ${n}` : `2026-07 payroll run ${n}`,
			before_state: isAccess ? null : { status: "approved" },
			after_state: isAccess ? null : { status: "posted" },
			resource_state: isAccess ? { report_type: "payroll_register", size_bytes: 2048 } : null,
			created_at: created.toISOString().replace(/\.\d{3}Z$/, ""),
		});
	});
}

function captureParams(url: URL): CapturedAuditListRequest {
	return {
		entity_type: url.searchParams.get("entity_type"),
		entity_id: url.searchParams.get("entity_id"),
		command: url.searchParams.get("command"),
		actor_user_id: url.searchParams.get("actor_user_id"),
		from: url.searchParams.get("from"),
		to: url.searchParams.get("to"),
		page: url.searchParams.get("page"),
		page_size: url.searchParams.get("page_size"),
	};
}

export function createAuditHandlers(options: AuditHandlersOptions = {}) {
	const pageSize = options.pageSize ?? 20;
	const store = new Map<string, AuditEventDetail>();
	const capturedListRequests: CapturedAuditListRequest[] = [];
	for (const event of options.empty ? [] : (options.events ?? defaultEvents(25))) {
		store.set(event.id, event);
	}

	const handlers = [
		http.get("/api/audit-events/filter-options", () => {
			const events = Array.from(store.values());
			const actorMap = new Map(
				events.flatMap((event) => (event.actor ? [[event.actor.id, event.actor] as const] : [])),
			);
			const body: AuditFilterOptions = {
				entity_types: Array.from(new Set(events.map((event) => event.entity_type))).sort(),
				commands: Array.from(new Set(events.map((event) => event.command))).sort(),
				actors: Array.from(actorMap.values()),
			};
			return HttpResponse.json(body);
		}),
		http.get("/api/audit-events", ({ request }) => {
			const url = new URL(request.url);
			capturedListRequests.push(captureParams(url));
			const entityType = url.searchParams.get("entity_type");
			const entityId = url.searchParams.get("entity_id");
			const command = url.searchParams.get("command");
			const actorUserId = url.searchParams.get("actor_user_id");
			const from = url.searchParams.get("from");
			const to = url.searchParams.get("to");
			const page = Number(url.searchParams.get("page") ?? "1");
			const size = Number(url.searchParams.get("page_size") ?? String(pageSize));
			let items = Array.from(store.values());
			if (entityType) items = items.filter((item) => item.entity_type === entityType);
			if (entityId) items = items.filter((item) => item.entity_id === entityId);
			if (command) items = items.filter((item) => item.command === command);
			if (actorUserId) items = items.filter((item) => item.actor?.id === actorUserId);
			if (from) items = items.filter((item) => Date.parse(item.created_at) >= Date.parse(from));
			if (to) items = items.filter((item) => Date.parse(item.created_at) <= Date.parse(to));
			items.sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at));
			const total = items.length;
			const totalPages = Math.max(1, Math.ceil(total / size));
			const start = (page - 1) * size;
			const body: PaginatedAuditEventResponse = {
				items: items.slice(start, start + size).map(listItem),
				total,
				page,
				page_size: size,
				total_pages: totalPages,
			};
			return HttpResponse.json(body);
		}),
		http.get("/api/audit-events/:eventId", ({ params }) => {
			const event = store.get(String(params.eventId));
			return event
				? HttpResponse.json(event)
				: HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
		}),
	];

	return { handlers, store, capturedListRequests };
}
