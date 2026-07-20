import {
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
	useSidebar,
} from "@/components/ui/sidebar";
import { useAuth } from "@/contexts/AuthContext";
import { APP_NAME, APP_SUBTITLE } from "@/lib/branding";

/** Non-interactive sidebar brand: product name + singleton org (ADR 0011). */
export function OrganizationBrand() {
	const { state, isMobile } = useSidebar();
	const { organization } = useAuth();
	const isCompactSidebar = state === "collapsed" && !isMobile;
	const compactInitial = APP_NAME.charAt(0).toUpperCase() || "A";

	return (
		<SidebarMenu>
			<SidebarMenuItem>
				<SidebarMenuButton size="lg" className="pointer-events-none cursor-default">
					{isCompactSidebar ? (
						<span className="flex h-full w-full items-center justify-center text-base font-semibold leading-none tracking-tight">
							{compactInitial}
						</span>
					) : null}
					<div className="grid flex-1 text-left text-sm leading-tight group-data-[collapsible=icon]:hidden">
						<span className="truncate text-sm font-medium">{APP_NAME}</span>
						<span className="truncate text-xs text-muted-foreground">
							{organization?.name ?? APP_SUBTITLE}
						</span>
					</div>
				</SidebarMenuButton>
			</SidebarMenuItem>
		</SidebarMenu>
	);
}
