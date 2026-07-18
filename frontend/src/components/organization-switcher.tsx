import { Check, ChevronsUpDown } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { CreateOrganizationDialog } from "@/components/create-organization-dialog";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
	useSidebar,
} from "@/components/ui/sidebar";
import { useAuth } from "@/contexts/AuthContext";
import { APP_NAME, APP_SUBTITLE } from "@/lib/branding";

export function OrganizationSwitcher() {
	const { state, isMobile } = useSidebar();
	const { activeOrganization, organizations, switchOrganization } = useAuth();
	const [menuOpen, setMenuOpen] = useState(false);
	const [createOpen, setCreateOpen] = useState(false);
	const [isSwitching, setIsSwitching] = useState(false);

	const isCompactSidebar = state === "collapsed" && !isMobile;
	const displayName = activeOrganization?.name ?? APP_NAME;
	const compactInitial = displayName.charAt(0).toUpperCase() || "O";

	const handleSwitch = async (organizationId: string) => {
		if (organizationId === activeOrganization?.id || isSwitching) return;
		setIsSwitching(true);
		try {
			await switchOrganization(organizationId);
			setMenuOpen(false);
		} catch (error) {
			toast.error("Unable to switch organization", {
				description: error instanceof Error ? error.message : "Please try again.",
			});
		} finally {
			setIsSwitching(false);
		}
	};

	return (
		<>
			<SidebarMenu>
				<SidebarMenuItem>
					<DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
						<DropdownMenuTrigger
							render={
								<SidebarMenuButton
									size="lg"
									className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
								/>
							}
						>
							{isCompactSidebar ? (
								<span className="flex h-full w-full items-center justify-center text-base font-semibold leading-none tracking-tight">
									{compactInitial}
								</span>
							) : null}
							<div className="grid flex-1 text-left text-sm leading-tight group-data-[collapsible=icon]:hidden">
								<span className="truncate text-sm font-medium">{displayName}</span>
								<span className="truncate text-xs text-muted-foreground">
									{activeOrganization ? APP_SUBTITLE : APP_NAME}
								</span>
							</div>
							<ChevronsUpDown className="ml-auto size-4 group-data-[collapsible=icon]:hidden" />
						</DropdownMenuTrigger>
						<DropdownMenuContent
							className="w-(--anchor-width) min-w-56 rounded-lg"
							align="start"
							side={isMobile ? "bottom" : "right"}
							sideOffset={4}
						>
							{organizations.map((organization) => {
								const isActive = organization.id === activeOrganization?.id;
								return (
									<DropdownMenuItem
										key={organization.id}
										disabled={isSwitching}
										onClick={() => {
											void handleSwitch(organization.id);
										}}
									>
										<span className="flex-1 truncate">{organization.name}</span>
										{isActive ? <Check className="size-4" /> : null}
									</DropdownMenuItem>
								);
							})}
							{organizations.length > 0 ? <DropdownMenuSeparator /> : null}
							<DropdownMenuItem
								onClick={() => {
									setMenuOpen(false);
									setCreateOpen(true);
								}}
							>
								<span>Add</span>
							</DropdownMenuItem>
						</DropdownMenuContent>
					</DropdownMenu>
				</SidebarMenuItem>
			</SidebarMenu>

			<CreateOrganizationDialog open={createOpen} onOpenChange={setCreateOpen} />
		</>
	);
}
