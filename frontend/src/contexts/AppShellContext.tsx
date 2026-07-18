import {
	createContext,
	type ReactNode,
	useCallback,
	useContext,
	useLayoutEffect,
	useMemo,
	useRef,
	useState,
} from "react";

/**
 * Tracks whether an `AppLayout` is rendered inside the persistent application shell.
 * Pages keep using `AppLayout`, but when they are under `ProtectedLayout` they publish
 * their header title/actions here instead of owning chrome DOM themselves.
 */
type AppShellHeader = {
	title: ReactNode;
	actions?: ReactNode;
};

type AppShellRegistration = {
	setHeader: (header: AppShellHeader) => symbol;
	clearHeader: (registrationId: symbol) => void;
};

const defaultHeader: AppShellHeader = { title: "Accord" };
const AppShellRegistrationContext = createContext<AppShellRegistration | null>(null);
const AppShellHeaderContext = createContext<AppShellHeader>(defaultHeader);

type AppShellProviderProps = {
	children: ReactNode;
};

export function AppShellProvider({ children }: AppShellProviderProps) {
	const [header, setHeaderState] = useState<AppShellHeader>(defaultHeader);
	const activeRegistrationRef = useRef<symbol | null>(null);

	const setHeader = useCallback((nextHeader: AppShellHeader) => {
		const registrationId = Symbol("app-shell-header");
		activeRegistrationRef.current = registrationId;
		setHeaderState((currentHeader) =>
			currentHeader.title === nextHeader.title && currentHeader.actions === nextHeader.actions
				? currentHeader
				: nextHeader,
		);
		return registrationId;
	}, []);

	const clearHeader = useCallback((registrationId: symbol) => {
		setHeaderState((currentHeader) => {
			if (activeRegistrationRef.current !== registrationId) return currentHeader;
			activeRegistrationRef.current = null;
			return defaultHeader;
		});
	}, []);

	const registration = useMemo(() => ({ setHeader, clearHeader }), [clearHeader, setHeader]);

	return (
		<AppShellRegistrationContext.Provider value={registration}>
			<AppShellHeaderContext.Provider value={header}>{children}</AppShellHeaderContext.Provider>
		</AppShellRegistrationContext.Provider>
	);
}

export function useInAppShell() {
	return useContext(AppShellRegistrationContext) !== null;
}

export function useAppShellHeader() {
	return useContext(AppShellHeaderContext);
}

export function useAppShellHeaderRegistration(title: ReactNode, actions?: ReactNode) {
	const registration = useContext(AppShellRegistrationContext);

	useLayoutEffect(() => {
		if (!registration) return;
		const registrationId = registration.setHeader({ title, actions });
		return () => registration.clearHeader(registrationId);
	}, [actions, registration, title]);
}
