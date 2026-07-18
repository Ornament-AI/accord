import { HttpResponse, http } from "msw";

import type { AuditEventResponse, PaginatedAuditEventResponse } from "@/lib/api/audit";

export type AuditHandlersOptions = {
	events?: AuditEventResponse[];
	pageSize?: number;
	/** When true, list always returns an empty page. */
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

export function buildAuditEvent(
	overrides: Partial<AuditEventResponse> & { id: string },
): AuditEventResponse {
	return {
		id: overrides.id,
		command: overrides.command ?? "submit",
		entity_type: overrides.entity_type ?? "payroll_run",
		entity_id: overrides.entity_id ?? "11111111-1111-1111-1111-111111111111",
		actor:
			overrides.actor === undefined
				? {
						id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
						name: "Ada Lovelace",
						email: "ada@example.com",
					}
				: overrides.actor,
		request_id: overrides.request_id ?? "req-001",
		summary: overrides.summary ?? { action: "submit", status: "submitted" },
		created_at: overrides.created_at ?? "2026-07-18T10:00:00",
	};
}

function defaultEvents(count: number): AuditEventResponse[] {
	return Array.from({ length: count }, (_, index) => {
		const n = index + 1;
		const created = new Date(Date.UTC(2026, 6, 18, 12, 0, 0));
		created.setUTCMinutes(created.getUTCMinutes() - index);
		const command =
			index % 5 === 0
				? "payroll_run.post"
				: index % 5 === 1
					? "artifact.download"
					: index % 5 === 2
						? "auth.login"
						: index % 5 === 3
							? "approve"
							: "submit";
		return buildAuditEvent({
			id: `aaaaaaaa-bbbb-cccc-dddd-${String(n).padStart(12, "0")}`,
			command,
			entity_type: command.startsWith("artifact.") ? "export_artifact" : "payroll_run",
			entity_id: `22222222-2222-2222-2222-${String(n).padStart(12, "0")}`,
			actor:
				index % 7 === 0
					? null
					: {
							id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
							name: index === 0 ? "Ada Lovelace" : `Actor ${n}`,
							email: index === 0 ? "ada@example.com" : `actor${n}@example.com`,
						},
			request_id: `req-${String(n).padStart(3, "0")}`,
			summary: {
				action: command,
				version: n,
				note: `Event ${n}`,
			},
			created_at: created.toISOString().replace(/\.\d{3}Z$/, ""),
		});
	});
}

export function createAuditHandlers(options: AuditHandlersOptions = {}) {
	const pageSize = options.pageSize ?? 20;
	const store = new Map<string, AuditEventResponse>();
	const capturedListRequests: CapturedAuditListRequest[] = [];

	const seed = options.empty ? [] : (options.events ?? defaultEvents(25));
	for (const event of seed) {
		store.set(event.id, event);
	}

	const handlers = [
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

			if (entityType) {
				items = items.filter((item) => item.entity_type === entityType);
			}
			if (entityId) {
				items = items.filter((item) => item.entity_id === entityId);
			}
			if (command) {
				items = items.filter((item) => item.command === command);
			}
			if (actorUserId) {
				items = items.filter((item) => item.actor?.id === actorUserId);
			}
			if (from) {
				const fromMs = Date.parse(from);
				if (!Number.isNaN(fromMs)) {
					items = items.filter((item) => Date.parse(item.created_at) >= fromMs);
				}
			}
			if (to) {
				const toMs = Date.parse(to);
				if (!Number.isNaN(toMs)) {
					items = items.filter((item) => Date.parse(item.created_at) <= toMs);
				}
			}

			// Newest-first (matches backend order_by created_at.desc, id.desc).
			items.sort((a, b) => {
				const byTime = Date.parse(b.created_at) - Date.parse(a.created_at);
				if (byTime !== 0) return byTime;
				return b.id.localeCompare(a.id);
			});

			const total = items.length;
			const totalPages = Math.max(1, Math.ceil(total / size) || 1);
			const start = (page - 1) * size;
			const pageItems = items.slice(start, start + size);

			const body: PaginatedAuditEventResponse = {
				items: pageItems,
				total,
				page,
				page_size: size,
				total_pages: total === 0 ? 1 : totalPages,
			};
			return HttpResponse.json(body);
		}),

		http.get("/api/audit-events/:eventId", ({ params }) => {
			const eventId = String(params.eventId);
			const event = store.get(eventId);
			if (!event) {
				return HttpResponse.json({ detail: "Not found", error: "NotFound" }, { status: 404 });
			}
			return HttpResponse.json(event);
		}),
	];

	return { handlers, store, capturedListRequests };
}
