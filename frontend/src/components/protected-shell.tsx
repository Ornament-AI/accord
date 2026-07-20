import type { CSSProperties, ReactNode } from "react";
import { Suspense, useEffect } from "react";
import { useLocation, useMatches, useOutlet } from "react-router";

import { AppSidebar } from "@/components/app-sidebar";
import { PageSkeleton } from "@/components/page-skeleton";
import { SiteHeader } from "@/components/site-header";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { useAppShellHeader } from "@/contexts/AppShellContext";
import { AnimatePresence, m, pageTransition, pageTransitionConfig } from "@/lib/motion";

type RouteTransitionHandle = {
	stableRouteTransition?: boolean;
};

function RouteScrollReset() {
	const location = useLocation();
	const routeKey = `${location.pathname}${location.search}`;

	useEffect(() => {
		if (!routeKey) {
			return;
		}
		window.scrollTo(0, 0);
	}, [routeKey]);

	return null;
}

function hasStableRouteTransition(handle: unknown): handle is RouteTransitionHandle {
	return Boolean(
		handle &&
			typeof handle === "object" &&
			"stableRouteTransition" in handle &&
			(handle as RouteTransitionHandle).stableRouteTransition,
	);
}

const routeContentClassName = "relative flex min-h-0 min-w-0 flex-1 flex-col";

function RouteSuspense({ children }: { children: ReactNode }) {
	return (
		<Suspense fallback={<PageSkeleton className="p-4 md:py-6 lg:px-6" />}>{children}</Suspense>
	);
}

/**
 * Table-heavy routes skip AnimatePresence entirely. Even zero-duration exit
 * variants still go through AnimatePresence's wait lifecycle, which leaves a
 * blank content frame while the previous page unmounts — that reads as flicker
 * on large data tables with sticky columns and skeleton swaps.
 */
function StableRouteOutlet() {
	const location = useLocation();
	const outlet = useOutlet();

	return (
		<div
			key={location.pathname}
			data-route-path={location.pathname}
			data-route-transition="page"
			data-route-transition-mode="stable"
			className={routeContentClassName}
		>
			<RouteSuspense>{outlet}</RouteSuspense>
		</div>
	);
}

/**
 * Lightweight routes use AnimatePresence for a short enter/exit crossfade.
 * `useOutlet()` captures the resolved element so the previous page can animate
 * out before the next one enters.
 */
function AnimatedRouteOutlet() {
	const location = useLocation();
	const outlet = useOutlet();

	return (
		<AnimatePresence mode="wait" initial={false}>
			<m.div
				key={location.pathname}
				data-route-path={location.pathname}
				data-route-transition="page"
				data-route-transition-mode="animated"
				className={routeContentClassName}
				variants={pageTransition}
				initial="hidden"
				animate="visible"
				exit="exit"
				transition={pageTransitionConfig}
			>
				<RouteSuspense>{outlet}</RouteSuspense>
			</m.div>
		</AnimatePresence>
	);
}

function AnimatedOutlet() {
	const matches = useMatches();
	const stableRouteTransition = matches.some((match) => hasStableRouteTransition(match.handle));

	return stableRouteTransition ? <StableRouteOutlet /> : <AnimatedRouteOutlet />;
}

// Consuming the header context here (rather than in ProtectedShell) keeps header
// updates from re-rendering the routed page subtree. Pages publish their header via
// `setHeader` on every render; if the page-rendering shell consumed that context it
// would re-render the active page, producing a fresh `actions` element and triggering
// another `setHeader` — an update loop that detaches header buttons mid-click.
function SiteHeaderHost() {
	const header = useAppShellHeader();
	return <SiteHeader title={header.title} actions={header.actions} />;
}

export function ProtectedShell() {
	return (
		<SidebarProvider
			style={{ "--header-height": "calc(var(--spacing) * 12)" } as CSSProperties}
			className="min-h-screen w-full min-w-0 bg-background text-foreground"
		>
			<AppSidebar variant="inset" />
			<SidebarInset className="flex min-h-0 min-w-0 flex-col overflow-x-hidden">
				<SiteHeaderHost />
				<RouteScrollReset />
				<AnimatedOutlet />
			</SidebarInset>
		</SidebarProvider>
	);
}
