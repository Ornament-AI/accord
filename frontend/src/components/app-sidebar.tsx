import { CaretRightIcon as ChevronRight } from "@phosphor-icons/react/dist/csr/CaretRight";
import type * as React from "react";
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router";
import { toast } from "sonner";

import { NavUser } from "@/components/nav-user";
import { OrganizationBrand } from "@/components/organization-brand";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuGroup,
	DropdownMenuLabel,
	DropdownMenuLinkItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
import { NAV_REGISTRY, type NavRegistryEntry } from "@/lib/nav-registry";
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
	const sectionActive = visibleChildren.some((child) => isPathActive(pathname, child.path));
	const [open, setOpen] = useState(sectionActive);

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
				<DropdownMenu>
					<DropdownMenuTrigger
						render={
							<SidebarMenuButton
								tooltip={item.title}
								isActive={false}
								className="data-popup-open:bg-sidebar-accent data-popup-open:text-sidebar-accent-foreground"
							/>
						}
					>
						<item.icon />
						<span>{item.title}</span>
					</DropdownMenuTrigger>
					<DropdownMenuContent
						side="right"
						align="start"
						sideOffset={4}
						className="min-w-44 rounded-lg"
					>
						<DropdownMenuGroup>
							<DropdownMenuLabel className="px-2 pb-1 pt-1.5 text-[length:var(--text-caption)] font-normal text-muted-foreground">
								{item.title}
							</DropdownMenuLabel>
							{visibleChildren.map((child) => (
								<DropdownMenuLinkItem
									key={child.path}
									render={<Link to={child.path} />}
									data-active={isPathActive(pathname, child.path) || undefined}
									className="rounded-md data-[active=true]:bg-accent data-[active=true]:text-accent-foreground"
								>
									{child.title}
								</DropdownMenuLinkItem>
							))}
						</DropdownMenuGroup>
					</DropdownMenuContent>
				</DropdownMenu>
			</SidebarMenuItem>
		);
	}

	return (
		<SidebarMenuItem>
			<Collapsible open={open} onOpenChange={setOpen} className="group/collapsible">
				<CollapsibleTrigger render={<SidebarMenuButton tooltip={item.title} isActive={false} />}>
					<item.icon />
					<span>{item.title}</span>
					<ChevronRight className="ml-auto text-muted-foreground! transition-transform group-data-[state=open]/collapsible:rotate-90" />
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
				<OrganizationBrand />
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
