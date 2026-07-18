import {
	createContext,
	type ReactNode,
	use,
	useCallback,
	useEffect,
	useMemo,
	useState,
} from "react";
import { fetchJson, fetchVoid } from "@/lib/api/http";
import { resolveApiUrl } from "@/lib/api-url";
import { queryClient } from "@/lib/query-client";
import type {
	ActiveOrganization,
	AuthMeResponse,
	AuthUser,
	Capability,
	CreateOrganizationInput,
	OrganizationMembership,
} from "@/types/auth";

export type { AuthUser } from "@/types/auth";

interface AuthContextType {
	user: AuthUser | null;
	activeOrganization: ActiveOrganization | null;
	organizations: OrganizationMembership[];
	isLoading: boolean;
	/** Monotonic counter bumped on org switch / create / logout to remount the shell subtree. */
	shellEpoch: number;
	hasCapability: (capability: Capability) => boolean;
	switchOrganization: (organizationId: string) => Promise<void>;
	createOrganization: (input: CreateOrganizationInput) => Promise<AuthMeResponse>;
	logout: () => Promise<void>;
	refetch: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function parseOrganizationMembership(value: unknown): OrganizationMembership | null {
	if (!isRecord(value)) return null;
	const id = typeof value.id === "string" ? value.id : null;
	const name = typeof value.name === "string" ? value.name : null;
	const slug = typeof value.slug === "string" ? value.slug : null;
	const role = typeof value.role === "string" ? value.role : null;
	if (!id || !name || !slug || !role) return null;
	return { id, name, slug, role };
}

function parseActiveOrganization(value: unknown): ActiveOrganization | null {
	const membership = parseOrganizationMembership(value);
	if (!membership || !isRecord(value)) return null;
	const capabilities = Array.isArray(value.capabilities)
		? value.capabilities.filter((item): item is string => typeof item === "string")
		: null;
	if (!capabilities) return null;
	return { ...membership, capabilities };
}

function parseAuthMeResponse(payload: unknown): AuthMeResponse | null {
	if (!isRecord(payload)) return null;
	const id = typeof payload.id === "string" ? payload.id : null;
	const email = typeof payload.email === "string" ? payload.email : null;
	const name = typeof payload.name === "string" ? payload.name : null;
	const isPlatformAdmin =
		typeof payload.is_platform_admin === "boolean" ? payload.is_platform_admin : null;
	if (!id || !email || !name || isPlatformAdmin === null) return null;

	const activeOrganization =
		payload.active_organization === null
			? null
			: parseActiveOrganization(payload.active_organization);
	if (payload.active_organization !== null && activeOrganization === null) return null;

	if (!Array.isArray(payload.organizations)) return null;
	const organizations: OrganizationMembership[] = [];
	for (const item of payload.organizations) {
		const membership = parseOrganizationMembership(item);
		if (!membership) return null;
		organizations.push(membership);
	}

	return {
		id,
		email,
		name,
		is_platform_admin: isPlatformAdmin,
		active_organization: activeOrganization,
		organizations,
	};
}

async function fetchCurrentUser(): Promise<AuthMeResponse | null> {
	try {
		const response = await fetch(resolveApiUrl("/api/auth/me"), {
			credentials: "include",
		});
		if (!response.ok) return null;
		const payload: unknown = await response.json();
		return parseAuthMeResponse(payload);
	} catch {
		return null;
	}
}

function toAuthUser(me: AuthMeResponse): AuthUser {
	return {
		id: me.id,
		email: me.email,
		name: me.name,
		is_platform_admin: me.is_platform_admin,
	};
}

export function AuthProvider({ children }: { children: ReactNode }) {
	const [user, setUser] = useState<AuthUser | null>(null);
	const [activeOrganization, setActiveOrganization] = useState<ActiveOrganization | null>(null);
	const [organizations, setOrganizations] = useState<OrganizationMembership[]>([]);
	const [isLoading, setIsLoading] = useState(true);
	const [shellEpoch, setShellEpoch] = useState(0);

	const applyMeResponse = useCallback((me: AuthMeResponse) => {
		setUser(toAuthUser(me));
		setActiveOrganization(me.active_organization);
		setOrganizations(me.organizations);
	}, []);

	const clearAuthState = useCallback(() => {
		setUser(null);
		setActiveOrganization(null);
		setOrganizations([]);
	}, []);

	const loadUser = useCallback(async () => {
		setIsLoading(true);
		const me = await fetchCurrentUser();
		if (me) {
			applyMeResponse(me);
		} else {
			clearAuthState();
		}
		setIsLoading(false);
	}, [applyMeResponse, clearAuthState]);

	useEffect(() => {
		void loadUser();
	}, [loadUser]);

	const refetch = useCallback(() => {
		void loadUser();
	}, [loadUser]);

	const hasCapability = useCallback(
		(capability: Capability) => {
			return Boolean(activeOrganization?.capabilities.includes(capability));
		},
		[activeOrganization],
	);

	const remountShell = useCallback(() => {
		queryClient.clear();
		setShellEpoch((epoch) => epoch + 1);
	}, []);

	const switchOrganization = useCallback(
		async (organizationId: string) => {
			const me = await fetchJson<AuthMeResponse>("/api/auth/switch-organization", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ organization_id: organizationId }),
			});
			const parsed = parseAuthMeResponse(me);
			if (!parsed) {
				throw new Error("Received an invalid switch-organization response.");
			}
			applyMeResponse(parsed);
			remountShell();
		},
		[applyMeResponse, remountShell],
	);

	const createOrganization = useCallback(
		async (input: CreateOrganizationInput) => {
			const me = await fetchJson<AuthMeResponse>("/api/organizations", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ name: input.name, slug: input.slug }),
			});
			const parsed = parseAuthMeResponse(me);
			if (!parsed) {
				throw new Error("Received an invalid create-organization response.");
			}
			applyMeResponse(parsed);
			remountShell();
			return parsed;
		},
		[applyMeResponse, remountShell],
	);

	const logout = useCallback(async () => {
		try {
			await fetchVoid("/api/auth/logout", { method: "POST" });
		} catch {
			// Still clear local session state even if the network call fails.
		}
		clearAuthState();
		remountShell();
		window.location.assign("/login");
	}, [clearAuthState, remountShell]);

	const value = useMemo<AuthContextType>(
		() => ({
			user,
			activeOrganization,
			organizations,
			isLoading,
			shellEpoch,
			hasCapability,
			switchOrganization,
			createOrganization,
			logout,
			refetch,
		}),
		[
			user,
			activeOrganization,
			organizations,
			isLoading,
			shellEpoch,
			hasCapability,
			switchOrganization,
			createOrganization,
			logout,
			refetch,
		],
	);

	return <AuthContext value={value}>{children}</AuthContext>;
}

/**
 * Remounts the app shell subtree when `shellEpoch` changes (org switch / create / logout).
 * Kept as a child of AuthProvider so the provider itself (and its /me fetch) does not remount.
 */
export function AuthShellBoundary({ children }: { children: ReactNode }) {
	const { shellEpoch } = useAuth();
	return <div key={shellEpoch}>{children}</div>;
}

export function useAuth() {
	const context = use(AuthContext);
	if (!context) {
		throw new Error("useAuth must be used within an AuthProvider");
	}
	return context;
}
