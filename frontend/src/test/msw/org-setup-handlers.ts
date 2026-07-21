import { HttpResponse, http } from "msw";

import type {
	OfficeCreate,
	OfficeResponse,
	OfficeUpdate,
	PostCreate,
	PostResponse,
	PostUpdate,
} from "@/lib/api/org-structure";

export type OrgSetupHandlersOptions = {
	offices?: OfficeResponse[];
	posts?: PostResponse[];
	/** When set, POST create endpoints return this status/body (e.g. 409). */
	createError?: { status: number; body: Record<string, unknown> };
};

const NOW = "2026-01-15T10:00:00Z";

export function buildOffice(
	overrides: Partial<OfficeResponse> & Pick<OfficeResponse, "id" | "name">,
): OfficeResponse {
	return {
		id: overrides.id,
		name: overrides.name,
		jurisdiction: overrides.jurisdiction ?? "mumbai",
		created_at: overrides.created_at ?? NOW,
		updated_at: overrides.updated_at ?? NOW,
	};
}

export function buildPost(
	overrides: Partial<PostResponse> & Pick<PostResponse, "id" | "designation">,
): PostResponse {
	return {
		id: overrides.id,
		designation: overrides.designation,
		class_name: overrides.class_name ?? "Class I",
		created_at: overrides.created_at ?? NOW,
		updated_at: overrides.updated_at ?? NOW,
	};
}

export function createOrgSetupHandlers(options: OrgSetupHandlersOptions = {}) {
	const offices = new Map<string, OfficeResponse>();
	const posts = new Map<string, PostResponse>();

	const seedOffices = options.offices ?? [
		buildOffice({ id: "office-1", name: "Head Office", jurisdiction: "mumbai" }),
		buildOffice({
			id: "office-2",
			name: "Nagpur Regional",
			jurisdiction: "nagpur",
		}),
	];
	for (const office of seedOffices) offices.set(office.id, office);

	const seedPosts = options.posts ?? [
		buildPost({ id: "post-1", designation: "Clerk", class_name: "Class III" }),
		buildPost({ id: "post-2", designation: "Officer", class_name: "Class I" }),
	];
	for (const post of seedPosts) posts.set(post.id, post);

	const handlers = [
		http.get("/api/offices", () => HttpResponse.json(Array.from(offices.values()))),
		http.post("/api/offices", async ({ request }) => {
			if (options.createError) {
				return HttpResponse.json(options.createError.body, { status: options.createError.status });
			}
			const body = (await request.json()) as OfficeCreate;
			const created = buildOffice({
				id: `office-new-${offices.size + 1}`,
				name: body.name,
				jurisdiction: body.jurisdiction,
			});
			offices.set(created.id, created);
			return HttpResponse.json(created, { status: 201 });
		}),
		http.patch("/api/offices/:officeId", async ({ params, request }) => {
			const officeId = String(params.officeId);
			const existing = offices.get(officeId);
			if (!existing) {
				return HttpResponse.json({ detail: "Not found" }, { status: 404 });
			}
			const body = (await request.json()) as OfficeUpdate;
			const updated: OfficeResponse = {
				...existing,
				name: body.name ?? existing.name,
				jurisdiction: body.jurisdiction ?? existing.jurisdiction,
				updated_at: NOW,
			};
			offices.set(officeId, updated);
			return HttpResponse.json(updated);
		}),

		http.get("/api/posts", () => HttpResponse.json(Array.from(posts.values()))),
		http.post("/api/posts", async ({ request }) => {
			if (options.createError) {
				return HttpResponse.json(options.createError.body, { status: options.createError.status });
			}
			const body = (await request.json()) as PostCreate;
			const exists = Array.from(posts.values()).some(
				(item) => item.designation === body.designation,
			);
			if (exists) {
				return HttpResponse.json(
					{ detail: "Post designation already exists", error: "ConflictError" },
					{ status: 409 },
				);
			}
			const created = buildPost({
				id: `post-new-${posts.size + 1}`,
				designation: body.designation,
				class_name: body.class_name,
			});
			posts.set(created.id, created);
			return HttpResponse.json(created, { status: 201 });
		}),
		http.patch("/api/posts/:postId", async ({ params, request }) => {
			const postId = String(params.postId);
			const existing = posts.get(postId);
			if (!existing) {
				return HttpResponse.json({ detail: "Not found" }, { status: 404 });
			}
			const body = (await request.json()) as PostUpdate;
			const updated: PostResponse = {
				...existing,
				class_name: body.class_name ?? existing.class_name,
				updated_at: NOW,
			};
			posts.set(postId, updated);
			return HttpResponse.json(updated);
		}),
	];

	return {
		handlers,
		stores: { offices, posts },
	};
}
