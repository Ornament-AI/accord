import { LayoutDashboard } from "lucide-react";
import type * as React from "react";
import { Link, useLocation } from "react-router";
import { toast } from "sonner";
import { NavUser } from "@/components/nav-user";
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
import { APP_NAME, APP_ORGANIZATION, APP_SUBTITLE } from "@/lib/branding";

const primaryNavItems = [{ title: "Dashboard", icon: LayoutDashboard, path: "/" }] as const;

function isPathActive(currentPath: string, itemPath: string) {
	if (itemPath === "/") {
		return currentPath === "/";
	}
	return currentPath === itemPath || currentPath.startsWith(`${itemPath}/`);
}

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
	const { state, isMobile } = useSidebar();
	const location = useLocation();
	const { user, logout } = useAuth();

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
	const compactBrandInitial = APP_NAME.charAt(0).toUpperCase();

	return (
		<Sidebar collapsible="icon" {...props}>
			<SidebarHeader>
				<SidebarMenu>
					<SidebarMenuItem>
						<SidebarMenuButton size="lg" className="pointer-events-none select-none">
							{isCompactSidebar ? (
								<span className="flex h-full w-full items-center justify-center text-base font-semibold leading-none tracking-tight">
									{compactBrandInitial}
								</span>
							) : null}
							<div className="grid flex-1 text-left text-sm leading-tight group-data-[collapsible=icon]:hidden">
								<span className="truncate text-sm font-medium">{APP_NAME}</span>
								<span className="truncate text-xs text-muted-foreground">{APP_SUBTITLE}</span>
							</div>
						</SidebarMenuButton>
					</SidebarMenuItem>
				</SidebarMenu>
			</SidebarHeader>

			<SidebarContent className="scroll-fade">
				<SidebarGroup>
					<SidebarGroupContent>
						<SidebarMenu>
							{primaryNavItems.map((item) => (
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
						organization: APP_ORGANIZATION,
					}}
					onSignOut={handleSignOut}
				/>
			</SidebarFooter>

			<SidebarRail />
		</Sidebar>
	);
}
