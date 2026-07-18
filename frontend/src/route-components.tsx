import { lazy, Suspense, useEffect } from "react";
import { Navigate, useLocation, useRouteError } from "react-router";

import { LoadingState } from "@/components/loading-state";
import { AppShellProvider } from "@/contexts/AppShellContext";
import { useAuth } from "@/contexts/AuthContext";
import { getErrorMessage } from "@/lib/errors";

const ProtectedShell = lazy(() =>
	import("@/components/protected-shell").then((mod) => ({ default: mod.ProtectedShell })),
);

export function ProtectedLayout() {
	const { user, isLoading } = useAuth();
	const location = useLocation();

	if (isLoading) {
		return <LoadingState />;
	}

	if (!user) {
		const returnTo = location.pathname + location.search + location.hash;
		return <Navigate to={`/login?returnTo=${encodeURIComponent(returnTo)}`} replace />;
	}

	return (
		<AppShellProvider>
			<Suspense fallback={<LoadingState />}>
				<ProtectedShell />
			</Suspense>
		</AppShellProvider>
	);
}

export function RouteErrorFallback() {
	const error = useRouteError();

	useEffect(() => {
		console.error("Router boundary error", error);
	}, [error]);

	return (
		<div className="flex min-h-screen items-center justify-center bg-background p-6">
			<div className="app-material-level-1 app-border-level-1 max-w-md rounded-lg border bg-card p-8 text-center">
				<h1 className="text-2xl font-semibold text-foreground">Something went wrong</h1>
				<p className="mt-3 text-sm text-muted-foreground">
					{getErrorMessage(error, "An unexpected error occurred")}
				</p>
				<button
					type="button"
					className="mt-5 inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring/35"
					onClick={() => window.location.reload()}
				>
					Reload
				</button>
			</div>
		</div>
	);
}

export const LoginPage = lazy(() => import("@/pages/LoginPage"));
export const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
export const NotFoundPage = lazy(() => import("@/pages/NotFoundPage"));
