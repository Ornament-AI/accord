import {
	createContext,
	type ReactNode,
	use,
	useCallback,
	useEffect,
	useMemo,
	useState,
} from "react";
import { resolveApiUrl } from "@/lib/api-url";
import { queryClient } from "@/lib/query-client";

export type AuthUser = {
	id: string;
	email: string;
	name?: string | null;
};

interface AuthContextType {
	user: AuthUser | null;
	isLoading: boolean;
	logout: () => Promise<void>;
	refetch: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

function parseAuthUser(payload: unknown): AuthUser | null {
	if (typeof payload !== "object" || payload === null) return null;
	const record = payload as Record<string, unknown>;
	const id = typeof record.id === "string" ? record.id : null;
	const email = typeof record.email === "string" ? record.email : null;
	if (!id || !email) return null;
	const name = typeof record.name === "string" || record.name === null ? record.name : undefined;
	return { id, email, name };
}

async function fetchCurrentUser(): Promise<AuthUser | null> {
	try {
		const response = await fetch(resolveApiUrl("/api/auth/me"), {
			credentials: "include",
		});
		if (!response.ok) return null;
		const payload: unknown = await response.json();
		return parseAuthUser(payload);
	} catch {
		return null;
	}
}

export function AuthProvider({ children }: { children: ReactNode }) {
	const [user, setUser] = useState<AuthUser | null>(null);
	const [isLoading, setIsLoading] = useState(true);

	const loadUser = useCallback(async () => {
		setIsLoading(true);
		const nextUser = await fetchCurrentUser();
		setUser(nextUser);
		setIsLoading(false);
	}, []);

	useEffect(() => {
		void loadUser();
	}, [loadUser]);

	const refetch = useCallback(() => {
		void loadUser();
	}, [loadUser]);

	const logout = useCallback(async () => {
		queryClient.clear();
		// TODO(auth): call POST /api/auth/logout once backend implements it
		window.location.href = "/login";
	}, []);

	const value = useMemo<AuthContextType>(
		() => ({
			user,
			isLoading,
			logout,
			refetch,
		}),
		[user, isLoading, logout, refetch],
	);

	return <AuthContext value={value}>{children}</AuthContext>;
}

export function useAuth() {
	const context = use(AuthContext);
	if (!context) {
		throw new Error("useAuth must be used within an AuthProvider");
	}
	return context;
}
