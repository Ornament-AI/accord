import {
	createContext,
	type ReactNode,
	use,
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
} from "react";
import { fetchVoid } from "@/lib/api/http";
import { resolveApiUrl } from "@/lib/api-url";
import { queryClient } from "@/lib/query-client";
import type {
	AccessState,
	ActiveOrganization,
	AuthMeResponse,
	AuthUser,
	Capability,
	MeMembership,
	MeOrganization,
} from "@/types/auth";

export type { AuthUser } from "@/types/auth";

interface AuthContextType {
	user: AuthUser | null;
	accessState: AccessState | null;
	organization: MeOrganization | null;
	membership: MeMembership | null;
	/** Convenience: organization + membership when access_state is active. */
	activeOrganization: ActiveOrganization | null;
	isLoading: boolean;
	shellEpoch: number;
	hasCapability: (capability: Capability) => boolean;
	logout: () => Promise<void>;
	refetch: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function parseOrganization(value: unknown): MeOrganization | null {
	if (!isRecord(value)) return null;
	const id = typeof value.id === "string" ? value.id : null;
	const name = typeof value.name === "string" ? value.name : null;
	const slug = typeof value.slug === "string" ? value.slug : null;
	if (!id || !name || !slug) return null;
	return { id, name, slug };
}

function parseMembership(value: unknown): MeMembership | null {
	if (!isRecord(value)) return null;
	const role = typeof value.role === "string" ? value.role : null;
	const capabilities = Array.isArray(value.capabilities)
		? value.capabilities.filter((item): item is string => typeof item === "string")
		: null;
	if (!role || !capabilities) return null;
	return { role, capabilities };
}

function parseAccessState(value: unknown): AccessState | null {
	if (value === "unbootstrapped" || value === "unprovisioned" || value === "active") {
		return value;
	}
	return null;
}

function parseAuthMeResponse(payload: unknown): AuthMeResponse | null {
	if (!isRecord(payload)) return null;
	const id = typeof payload.id === "string" ? payload.id : null;
	const email = typeof payload.email === "string" ? payload.email : null;
	const name = typeof payload.name === "string" ? payload.name : null;
	const isPlatformAdmin =
		typeof payload.is_platform_admin === "boolean" ? payload.is_platform_admin : null;
	const accessState = parseAccessState(payload.access_state);
	if (!id || !email || !name || isPlatformAdmin === null || !accessState) return null;

	const organization =
		payload.organization === null ? null : parseOrganization(payload.organization);
	if (payload.organization !== null && organization === null) return null;

	const membership = payload.membership === null ? null : parseMembership(payload.membership);
	if (payload.membership !== null && membership === null) return null;

	if (accessState === "unbootstrapped" && organization !== null) return null;
	if (accessState !== "unbootstrapped" && organization === null) return null;
	if (accessState === "active" && membership === null) return null;
	if (accessState !== "active" && membership !== null) return null;

	return {
		id,
		email,
		name,
		is_platform_admin: isPlatformAdmin,
		access_state: accessState,
		organization,
		membership,
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

function toActiveOrganization(me: AuthMeResponse): ActiveOrganization | null {
	if (me.access_state !== "active" || !me.organization || !me.membership) return null;
	return {
		...me.organization,
		role: me.membership.role,
		capabilities: me.membership.capabilities,
	};
}

export function AuthProvider({ children }: { children: ReactNode }) {
	const [user, setUser] = useState<AuthUser | null>(null);
	const [accessState, setAccessState] = useState<AccessState | null>(null);
	const [organization, setOrganization] = useState<MeOrganization | null>(null);
	const [membership, setMembership] = useState<MeMembership | null>(null);
	const [activeOrganization, setActiveOrganization] = useState<ActiveOrganization | null>(null);
	const [isLoading, setIsLoading] = useState(true);
	const [shellEpoch, setShellEpoch] = useState(0);
	const authSeq = useRef(0);

	const applyMeResponse = useCallback((me: AuthMeResponse) => {
		authSeq.current += 1;
		setUser(toAuthUser(me));
		setAccessState(me.access_state);
		setOrganization(me.organization);
		setMembership(me.membership);
		setActiveOrganization(toActiveOrganization(me));
	}, []);

	const clearAuthState = useCallback(() => {
		authSeq.current += 1;
		setUser(null);
		setAccessState(null);
		setOrganization(null);
		setMembership(null);
		setActiveOrganization(null);
	}, []);

	const loadUser = useCallback(async () => {
		const seq = authSeq.current;
		setIsLoading(true);
		const me = await fetchCurrentUser();
		if (authSeq.current !== seq) {
			setIsLoading(false);
			return;
		}
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
			accessState,
			organization,
			membership,
			activeOrganization,
			isLoading,
			shellEpoch,
			hasCapability,
			logout,
			refetch,
		}),
		[
			user,
			accessState,
			organization,
			membership,
			activeOrganization,
			isLoading,
			shellEpoch,
			hasCapability,
			logout,
			refetch,
		],
	);

	return <AuthContext value={value}>{children}</AuthContext>;
}

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
