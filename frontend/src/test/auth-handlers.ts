import { HttpResponse, http } from "msw";

import type { AuthMeResponse } from "@/types/auth";

import { buildAuthMe } from "./auth-fixtures";

type AuthHandlerOptions = {
	me?: AuthMeResponse | null;
	/** When true, GET /api/auth/me returns 401. */
	unauthenticated?: boolean;
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
	];

	return {
		handlers,
		getMe: () => currentMe,
		setMe: (me: AuthMeResponse | null) => {
			currentMe = me;
		},
	};
}
