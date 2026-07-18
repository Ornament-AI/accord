import { ChevronRight } from "lucide-react";
import type * as React from "react";
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router";
import { toast } from "sonner";

import { NavUser } from "@/components/nav-user";
import { OrganizationSwitcher } from "@/components/organization-switcher";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
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
	SidebarMenuSub,
	SidebarMenuSubButton,
	SidebarMenuSubItem,
	SidebarRail,
	useSidebar,
} from "@/components/ui/sidebar";
import { ThemeSwitcher } from "@/components/ui/theme-switcher";
import { useAuth } from "@/contexts/AuthContext";
import { type NavRegistryEntry, NAV_REGISTRY } from "@/lib/nav-registry";
import type { Capability } from "@/types/auth";

function isPathActive(currentPath: string, itemPath: string) {
	if (itemPath === "/") {
		return currentPath === "/";
	}
	return currentPath === itemPath || currentPath.startsWith(`${itemPath}/`);
}

function NavFolderItem({
	item,
	pathname,
	isCompactSidebar,
	hasCapability,
}: {
	item: NavRegistryEntry & { children: NonNullable<NavRegistryEntry["children"]> };
	pathname: string;
	isCompactSidebar: boolean;
	hasCapability: (capability: Capability) => boolean;
}) {
	const visibleChildren = item.children.filter(
		(child) => child.capability === undefined || hasCapability(child.capability),
	);
	const sectionActive = isPathActive(pathname, item.path);
	const [open, setOpen] = useState(sectionActive);
	const firstChildPath = visibleChildren[0]?.path ?? item.path;

	useEffect(() => {
		if (sectionActive) {
			setOpen(true);
		}
	}, [sectionActive]);

	if (visibleChildren.length === 0) {
		return null;
	}

	if (isCompactSidebar) {
		return (
			<SidebarMenuItem>
				<SidebarMenuButton
					render={<Link to={firstChildPath} />}
					tooltip={item.title}
					isActive={false}
				>
					<item.icon />
					<span>{item.title}</span>
				</SidebarMenuButton>
			</SidebarMenuItem>
		);
	}

	return (
		<SidebarMenuItem>
			<Collapsible open={open} onOpenChange={setOpen} className="group/collapsible">
				<CollapsibleTrigger
					render={<SidebarMenuButton tooltip={item.title} isActive={false} />}
				>
					<item.icon />
					<span>{item.title}</span>
					<ChevronRight className="ml-auto transition-transform group-data-[state=open]/collapsible:rotate-90" />
				</CollapsibleTrigger>
				<CollapsibleContent>
					<SidebarMenuSub>
						{visibleChildren.map((child) => (
							<SidebarMenuSubItem key={child.path}>
								<SidebarMenuSubButton
									render={<Link to={child.path} />}
									isActive={isPathActive(pathname, child.path)}
								>
									<span>{child.title}</span>
								</SidebarMenuSubButton>
							</SidebarMenuSubItem>
						))}
					</SidebarMenuSub>
				</CollapsibleContent>
			</Collapsible>
		</SidebarMenuItem>
	);
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
							{visibleNavItems.map((item) => {
								const children = item.children;
								if (children && children.length > 0) {
									return (
										<NavFolderItem
											key={item.title}
											item={{ ...item, children }}
											pathname={location.pathname}
											isCompactSidebar={isCompactSidebar}
											hasCapability={hasCapability}
										/>
									);
								}

								return (
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
								);
							})}
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
