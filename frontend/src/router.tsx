import { createBrowserRouter, type RouteObject } from "react-router";

import {
	AuditPage,
	AuthenticatedIndexRedirect,
	EmployeeDetailPage,
	EmployeeListPage,
	LoginPage,
	NotFoundPage,
	OfficesPage,
	OrgSetupIndexRedirect,
	PayComponentDetailPage,
	PayComponentsPage,
	PayRunDetailPage,
	PayRunsPage,
	PostsPage,
	ProtectedLayout,
	ReportsIndexRedirect,
	ReportsLayout,
	ReportSheetPage,
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
			{ index: true, element: <AuthenticatedIndexRedirect /> },
			{ path: "employees", element: <EmployeeListPage /> },
			{ path: "employees/:employeeId", element: <EmployeeDetailPage /> },
			{
				path: "organization",
				children: [
					{ index: true, element: <OrgSetupIndexRedirect /> },
					{ path: "offices", element: <OfficesPage /> },
					{ path: "posts", element: <PostsPage /> },
				],
			},
			{ path: "pay-components", element: <PayComponentsPage /> },
			{ path: "pay-components/:componentId", element: <PayComponentDetailPage /> },
			{ path: "pay-runs", element: <PayRunsPage /> },
			{ path: "pay-runs/:runId", element: <PayRunDetailPage /> },
			{
				path: "reports",
				element: <ReportsLayout />,
				children: [
					{ index: true, element: <ReportsIndexRedirect /> },
					{ path: ":reportSlug", element: <ReportSheetPage /> },
				],
			},
			{ path: "audit", element: <AuditPage /> },
			{ path: "*", element: <NotFoundPage /> },
		],
	},
];

export const router = createBrowserRouter(routes);
