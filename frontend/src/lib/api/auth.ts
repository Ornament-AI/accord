import { fetchPublicVoid } from "@/lib/api/http";
import type { components } from "@/types/api.generated";

type PasswordLoginRequest = components["schemas"]["PasswordLoginRequest"];
type MagicCodeRequest = components["schemas"]["MagicCodeRequest"];
type MagicCodeLoginRequest = components["schemas"]["MagicCodeLoginRequest"];

function postAuth(path: string, body: object): Promise<void> {
	return fetchPublicVoid(path, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function loginWithPassword(body: PasswordLoginRequest): Promise<void> {
	return postAuth("/api/auth/login/password", body);
}

export function requestMagicCode(body: MagicCodeRequest): Promise<void> {
	return postAuth("/api/auth/magic-code", body);
}

export function loginWithMagicCode(body: MagicCodeLoginRequest): Promise<void> {
	return postAuth("/api/auth/login/magic-code", body);
}
