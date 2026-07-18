import type * as React from "react";
import { Link, useLocation } from "react-router";
import { toast } from "sonner";

import { NavUser } from "@/components/nav-user";
import { OrganizationSwitcher } from "@/components/organization-switcher";
import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarGroup,
	SidebarGroupContent,
	SidebarHeader,
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
	SidebarRail,
	useSidebar,
} from "@/components/ui/sidebar";
import { ThemeSwitcher } from "@/components/ui/theme-switcher";
import { useAuth } from "@/contexts/AuthContext";
import { NAV_REGISTRY } from "@/lib/nav-registry";

function isPathActive(currentPath: string, itemPath: string) {
	if (itemPath === "/") {
		return currentPath === "/";
	}
	return currentPath === itemPath || currentPath.startsWith(`${itemPath}/`);
}

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
	const { state, isMobile } = useSidebar();
	const location = useLocation();
	const { user, activeOrganization, hasCapability, logout } = useAuth();

	const handleSignOut = async () => {
		try {
			await logout();
		} catch (error) {
			toast.error("Sign out failed", {
				description:
					error instanceof Error
						? error.message
						: "Unable to sign out right now. Please try again.",
			});
		}
	};

	const displayName = user?.name?.trim() || user?.email?.split("@")[0] || "User";
	const isCompactSidebar = state === "collapsed" && !isMobile;
	const visibleNavItems = NAV_REGISTRY.filter(
		(item) => item.capability === undefined || hasCapability(item.capability),
	);

	return (
		<Sidebar collapsible="icon" {...props}>
			<SidebarHeader>
				<OrganizationSwitcher />
			</SidebarHeader>

			<SidebarContent className="scroll-fade">
				<SidebarGroup>
					<SidebarGroupContent>
						<SidebarMenu>
							{visibleNavItems.map((item) => (
								<SidebarMenuItem key={item.title}>
									<SidebarMenuButton
										render={<Link to={item.path} />}
										tooltip={item.title}
										isActive={isPathActive(location.pathname, item.path)}
									>
										<item.icon />
										<span>{item.title}</span>
									</SidebarMenuButton>
								</SidebarMenuItem>
							))}
						</SidebarMenu>
					</SidebarGroupContent>
				</SidebarGroup>
			</SidebarContent>

			<SidebarFooter>
				<ThemeSwitcher compact={isCompactSidebar} className="mx-auto mb-1" />
				<NavUser
					user={{
						name: displayName,
						email: user?.email || "",
						organization: activeOrganization?.name ?? null,
						isPlatformAdmin: user?.is_platform_admin ?? false,
					}}
					onSignOut={handleSignOut}
				/>
			</SidebarFooter>

			<SidebarRail />
		</Sidebar>
	);
}
