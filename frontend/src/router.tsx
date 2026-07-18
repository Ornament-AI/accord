import { createBrowserRouter, type RouteObject } from "react-router";

import {
	DashboardPage,
	LoginPage,
	NotFoundPage,
	ProtectedLayout,
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
			{ path: "*", element: <NotFoundPage /> },
		],
	},
];

export const router = createBrowserRouter(routes);
