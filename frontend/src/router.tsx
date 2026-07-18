import { createBrowserRouter, type RouteObject } from "react-router";

import {
	AuditPage,
	DashboardPage,
	EmployeeDetailPage,
	EmployeeListPage,
	LoginPage,
	NotFoundPage,
	OrganizationSetupPage,
	PayComponentDetailPage,
	PayComponentsPage,
	PayRunDetailPage,
	PayRunsPage,
	ProtectedLayout,
	ReportsPage,
	RouteErrorFallback,
} from "@/route-components";

export const routes: RouteObject[] = [
	{
		path: "login",
		element: <LoginPage />,
		errorElement: <RouteErrorFallback />,
	},
	{
		path: "/",
		element: <ProtectedLayout />,
		errorElement: <RouteErrorFallback />,
		children: [
			{ index: true, element: <DashboardPage /> },
			{ path: "employees", element: <EmployeeListPage /> },
			{ path: "employees/:employeeId", element: <EmployeeDetailPage /> },
			{ path: "organization", element: <OrganizationSetupPage /> },
			{ path: "pay-components", element: <PayComponentsPage /> },
			{ path: "pay-components/:componentId", element: <PayComponentDetailPage /> },
			{ path: "pay-runs", element: <PayRunsPage /> },
			{ path: "pay-runs/:runId", element: <PayRunDetailPage /> },
			{ path: "reports", element: <ReportsPage /> },
			{ path: "audit", element: <AuditPage /> },
			{ path: "*", element: <NotFoundPage /> },
		],
	},
];

export const router = createBrowserRouter(routes);
