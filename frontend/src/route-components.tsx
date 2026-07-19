import { lazy, Suspense, useEffect } from "react";
import { Navigate, useLocation, useRouteError } from "react-router";

import { LoadingState } from "@/components/loading-state";
import { AppShellProvider } from "@/contexts/AppShellContext";
import { useAuth } from "@/contexts/AuthContext";
import { getErrorMessage } from "@/lib/errors";
import NoOrganizationPage from "@/pages/NoOrganizationPage";
import {
	EmployeeGroupsPage,
	OfficesPage,
	OrgSetupIndexRedirect,
	PayrollUnitsPage,
	PostsPage,
} from "@/pages/org-setup/OrgSetupPage";
import SelectOrganizationPage from "@/pages/SelectOrganizationPage";

const ProtectedShell = lazy(() =>
	import("@/components/protected-shell").then((mod) => ({ default: mod.ProtectedShell })),
);

export function ProtectedLayout() {
	const { user, isLoading, organizations, activeOrganization } = useAuth();
	const location = useLocation();

	if (isLoading) {
		return <LoadingState />;
	}

	if (!user) {
		const returnTo = location.pathname + location.search + location.hash;
		return <Navigate to={`/login?returnTo=${encodeURIComponent(returnTo)}`} replace />;
	}

	const hasNoOrganization = organizations.length === 0 && activeOrganization === null;
	if (hasNoOrganization) {
		return (
			<Suspense fallback={<LoadingState />}>
				<NoOrganizationPage />
			</Suspense>
		);
	}

	if (activeOrganization === null) {
		return <SelectOrganizationPage />;
	}

	return (
		<AppShellProvider>
			<Suspense fallback={<LoadingState />}>
				<ProtectedShell />
			</Suspense>
		</AppShellProvider>
	);
}

export function AuthenticatedIndexRedirect() {
	const { activeOrganization, hasCapability } = useAuth();

	if (activeOrganization === null) {
		return <SelectOrganizationPage />;
	}

	if (hasCapability("create_run")) {
		return <Navigate to="/pay-runs" replace />;
	}
	if (hasCapability("view_master_data")) {
		return <Navigate to="/employees" replace />;
	}
	if (hasCapability("generate_reports")) {
		return <Navigate to="/reports" replace />;
	}
	return <Navigate to="/audit" replace />;
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
export const EmployeeListPage = lazy(() => import("@/pages/employees/EmployeeListPage"));
export const EmployeeDetailPage = lazy(() => import("@/pages/employees/EmployeeDetailPage"));
export const PayComponentsPage = lazy(() => import("@/pages/pay-components/PayComponentsPage"));
export const PayComponentDetailPage = lazy(
	() => import("@/pages/pay-components/PayComponentDetailPage"),
);
export { EmployeeGroupsPage, OfficesPage, OrgSetupIndexRedirect, PayrollUnitsPage, PostsPage };
export const PayRunsPage = lazy(() => import("@/pages/pay-runs/PayRunsPage"));
export const PayRunDetailPage = lazy(() => import("@/pages/pay-runs/PayRunDetailPage"));
export const ReportsPage = lazy(() => import("@/pages/reports/ReportsPage"));
export const AuditPage = lazy(() => import("@/pages/audit/AuditPage"));
export { NoOrganizationPage, SelectOrganizationPage };
export const NotFoundPage = lazy(() => import("@/pages/NotFoundPage"));
