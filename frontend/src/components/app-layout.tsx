import type { CSSProperties, ReactNode } from "react";
import { AppSidebar } from "@/components/app-sidebar";
import { SiteHeader } from "@/components/site-header";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { useAppShellHeaderRegistration, useInAppShell } from "@/contexts/AppShellContext";

interface AppLayoutProps {
	title: ReactNode;
	children: ReactNode;
	actions?: ReactNode;
}

export function AppLayout({ title, children, actions }: AppLayoutProps) {
	const inAppShell = useInAppShell();
	useAppShellHeaderRegistration(title, actions);

	const pageContent = (
		<div className="relative flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>
	);

	// Inside the routed app the sidebar/header chrome and route transition are
	// owned by the persistent shell (see ProtectedLayout), so render only the
	// page body to avoid remounting chrome on navigation.
	if (inAppShell) {
		return pageContent;
	}

	// Standalone usage (e.g. a page rendered in isolation by a unit test): keep
	// the layout self-contained by providing its own chrome.
	return (
		<SidebarProvider
			style={{ "--header-height": "calc(var(--spacing) * 12)" } as CSSProperties}
			className="w-full min-w-0"
		>
			<AppSidebar variant="inset" />
			<SidebarInset className="flex min-w-0 flex-col overflow-x-hidden">
				<SiteHeader title={title} actions={actions} />
				{pageContent}
			</SidebarInset>
		</SidebarProvider>
	);
}
