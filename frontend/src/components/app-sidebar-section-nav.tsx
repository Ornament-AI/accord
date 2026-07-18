import { ChevronRight } from "lucide-react";
import type * as React from "react";
import { Link } from "react-router";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuGroup,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
	SidebarMenuButton,
	SidebarMenuItem,
	SidebarMenuSub,
	SidebarMenuSubButton,
	SidebarMenuSubItem,
} from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";

type SidebarSection = {
	id: string;
	title: string;
	path: string;
};

type AppSidebarSectionNavProps = {
	title: string;
	icon: React.ElementType;
	sections: readonly SidebarSection[];
	currentPath: string;
	isCompactSidebar: boolean;
	open: boolean;
	onOpenChange: (open: boolean) => void;
	submenuId: string;
	onNavigate: (path: string) => void;
};

export function AppSidebarSectionNav({
	title,
	icon: Icon,
	sections,
	currentPath,
	isCompactSidebar,
	open,
	onOpenChange,
	submenuId,
	onNavigate,
}: AppSidebarSectionNavProps) {
	if (isCompactSidebar) {
		return (
			<SidebarMenuItem>
				<DropdownMenu open={open} onOpenChange={onOpenChange}>
					<DropdownMenuTrigger
						render={
							<SidebarMenuButton
								aria-label={`Open ${title} sections`}
								className="data-[popup-open]:bg-sidebar-accent data-[popup-open]:text-sidebar-accent-foreground"
							/>
						}
					>
						<Icon />
						<span>{title}</span>
					</DropdownMenuTrigger>
					<DropdownMenuContent side="right" align="start" sideOffset={8} className="min-w-56">
						<DropdownMenuGroup>
							<DropdownMenuLabel>{title} sections</DropdownMenuLabel>
							{sections.map((section) => {
								const isActive = currentPath === section.path;
								return (
									<DropdownMenuItem
										key={section.id}
										aria-current={isActive ? "page" : undefined}
										className={cn(
											"cursor-pointer",
											isActive &&
												"bg-primary text-primary-foreground data-highlighted:bg-primary/90 data-highlighted:text-primary-foreground",
										)}
										onClick={() => onNavigate(section.path)}
									>
										<span>{section.title}</span>
									</DropdownMenuItem>
								);
							})}
						</DropdownMenuGroup>
					</DropdownMenuContent>
				</DropdownMenu>
			</SidebarMenuItem>
		);
	}

	return (
		<Collapsible open={open} onOpenChange={onOpenChange} render={<SidebarMenuItem />}>
			<CollapsibleTrigger
				render={
					<SidebarMenuButton
						tooltip={title}
						aria-label={open ? `Collapse ${title} navigation` : `Expand ${title} navigation`}
						aria-controls={submenuId}
					/>
				}
			>
				<Icon />
				<span>{title}</span>
				<ChevronRight className={cn("accord-motion-chevron ml-auto", open && "rotate-90")} />
			</CollapsibleTrigger>
			<CollapsibleContent id={submenuId}>
				<SidebarMenuSub aria-label={`${title} sections`}>
					{sections.map((section) => (
						<SidebarMenuSubItem key={section.id}>
							<SidebarMenuSubButton
								className="[&>span:last-child]:whitespace-nowrap"
								render={
									<Link
										to={section.path}
										aria-current={currentPath === section.path ? "page" : undefined}
									/>
								}
								isActive={currentPath === section.path}
							>
								<span>{section.title}</span>
							</SidebarMenuSubButton>
						</SidebarMenuSubItem>
					))}
				</SidebarMenuSub>
			</CollapsibleContent>
		</Collapsible>
	);
}
