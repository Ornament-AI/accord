import { HttpResponse, http } from "msw";

import type { AuthMeResponse } from "@/types/auth";

import { buildAuthMe } from "./auth-fixtures";

type ErrorResult = {
	status: number;
	body: Record<string, unknown>;
};

function isErrorResult(value: AuthMeResponse | ErrorResult): value is ErrorResult {
	return "status" in value && "body" in value && !("email" in value);
}

type AuthHandlerOptions = {
	me?: AuthMeResponse | null;
	/** When true, GET /api/auth/me returns 401. */
	unauthenticated?: boolean;
	onSwitchOrganization?: (organizationId: string) => AuthMeResponse | ErrorResult;
	/** Return an error, a me payload, or `undefined` to use the default create path. */
	onCreateOrganization?: (body: {
		name: string;
		slug: string;
	}) => AuthMeResponse | ErrorResult | undefined;
	onLogout?: () => void;
};

export function createAuthHandlers(options: AuthHandlerOptions = {}) {
	let currentMe: AuthMeResponse | null = options.unauthenticated
		? null
		: (options.me ?? buildAuthMe());

	const handlers = [
		http.get("/api/auth/me", () => {
			if (!currentMe) {
				return HttpResponse.json(
					{ detail: "Not authenticated", error: "Unauthenticated" },
					{ status: 401 },
				);
			}
			return HttpResponse.json(currentMe);
		}),

		http.post("/api/auth/logout", () => {
			options.onLogout?.();
			currentMe = null;
			return new HttpResponse(null, { status: 204 });
		}),

		http.post("/api/auth/switch-organization", async ({ request }) => {
			const body = (await request.json()) as { organization_id?: string };
			const organizationId = body.organization_id;
			if (!organizationId) {
				return HttpResponse.json({ detail: "organization_id is required" }, { status: 422 });
			}

			if (options.onSwitchOrganization) {
				const result = options.onSwitchOrganization(organizationId);
				if (isErrorResult(result)) {
					return HttpResponse.json(result.body, { status: result.status });
				}
				currentMe = result;
				return HttpResponse.json(result);
			}

			if (!currentMe) {
				return HttpResponse.json({ detail: "Not authenticated" }, { status: 401 });
			}

			const membership = currentMe.organizations.find((org) => org.id === organizationId);
			if (!membership) {
				return HttpResponse.json(
					{ detail: "Not a member of that organization", error: "Forbidden" },
					{ status: 403 },
				);
			}

			currentMe = {
				...currentMe,
				active_organization: {
					...membership,
					capabilities: currentMe.active_organization?.capabilities ?? [],
				},
			};
			return HttpResponse.json(currentMe);
		}),

		http.post("/api/organizations", async ({ request }) => {
			const body = (await request.json()) as { name?: string; slug?: string };
			const name = body.name?.trim() ?? "";
			const slug = body.slug?.trim() ?? "";

			if (options.onCreateOrganization) {
				const result = options.onCreateOrganization({ name, slug });
				if (result !== undefined) {
					if (isErrorResult(result)) {
						return HttpResponse.json(result.body, { status: result.status });
					}
					currentMe = result;
					return HttpResponse.json(result, { status: 201 });
				}
			}

			if (!currentMe) {
				return HttpResponse.json({ detail: "Not authenticated" }, { status: 401 });
			}

			if (currentMe.organizations.some((org) => org.slug === slug)) {
				return HttpResponse.json(
					{ detail: "Organization slug already taken", error: "Conflict" },
					{ status: 409 },
				);
			}

			const created = {
				id: `org-${slug}`,
				name,
				slug,
				role: "organization_administrator",
			};
			currentMe = {
				...currentMe,
				active_organization: {
					...created,
					capabilities: [
						"manage_organization",
						"manage_members",
						"manage_master_data",
						"view_master_data",
						"create_run",
						"generate_reports",
						"view_audit",
					],
				},
				organizations: [...currentMe.organizations, created],
			};
			return HttpResponse.json(currentMe, { status: 201 });
		}),
	];

	return {
		handlers,
		getMe: () => currentMe,
		setMe: (me: AuthMeResponse | null) => {
			currentMe = me;
		},
	};
}
