import { DotsThreeOutlineVerticalIcon as EllipsisVertical } from "@phosphor-icons/react/dist/csr/DotsThreeOutlineVertical";
import { SignOutIcon as LogOut } from "@phosphor-icons/react/dist/csr/SignOut";
import * as React from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuGroup,
	DropdownMenuItem,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Separator } from "@/components/ui/separator";
import {
	Sheet,
	SheetContent,
	SheetDescription,
	SheetHeader,
	SheetTitle,
	SheetTrigger,
} from "@/components/ui/sheet";
import {
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
	useSidebar,
} from "@/components/ui/sidebar";
import { APP_ORGANIZATION } from "@/lib/branding";

export function NavUser({
	user,
	onSignOut,
}: {
	user: {
		name?: string;
		email: string;
		organization?: string | null;
		isPlatformAdmin?: boolean;
		avatar?: string;
	};
	onSignOut: () => void;
}) {
	const { isMobile } = useSidebar();
	const [open, setOpen] = React.useState(false);
	const fallbackName = user.name?.trim() || user.email.split("@")[0] || "User";
	const organizationLabel = user.organization?.trim() || APP_ORGANIZATION;
	const initials = fallbackName
		.split(" ")
		.filter(Boolean)
		.map((part) => part[0])
		.join("")
		.slice(0, 2)
		.toUpperCase();

	const triggerContent = (
		<>
			<Avatar className="size-8 rounded-lg">
				<AvatarImage src={user.avatar} alt={fallbackName} />
				<AvatarFallback className="rounded-lg">{initials || "U"}</AvatarFallback>
			</Avatar>
			<div className="grid flex-1 text-left text-sm leading-tight">
				<span className="truncate font-medium">{fallbackName}</span>
			</div>
			<EllipsisVertical className="ml-auto size-4" />
		</>
	);

	const userInfoPanel = (
		<div className="grid gap-2 p-2">
			<div className="grid gap-0.5">
				<span className="text-[length:var(--text-caption)] text-muted-foreground">Email</span>
				<span className="truncate text-sm">{user.email}</span>
			</div>
			<div className="grid gap-0.5">
				<span className="text-[length:var(--text-caption)] text-muted-foreground">
					Organization
				</span>
				<span className="truncate text-sm">{organizationLabel}</span>
			</div>
			{user.isPlatformAdmin ? (
				<div className="grid gap-0.5">
					<span className="text-[length:var(--text-caption)] text-muted-foreground">Access</span>
					<span className="truncate text-sm">Platform Admin</span>
				</div>
			) : null}
		</div>
	);

	return (
		<SidebarMenu>
			<SidebarMenuItem>
				{isMobile ? (
					<Sheet open={open} onOpenChange={setOpen}>
						<SheetTrigger
							render={
								<SidebarMenuButton
									size="lg"
									className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
								/>
							}
						>
							{triggerContent}
						</SheetTrigger>
						<SheetContent side="bottom" className="rounded-t-lg gap-2 px-4 pt-10 pb-6">
							<SheetHeader className="sr-only">
								<SheetTitle>Account</SheetTitle>
								<SheetDescription>Your account information.</SheetDescription>
							</SheetHeader>
							{userInfoPanel}
							<Separator />
							<button
								type="button"
								className="flex w-full items-center gap-2 rounded-md p-2 text-sm text-destructive outline-none hover:bg-destructive/10 focus-visible:ring-2 focus-visible:ring-ring/35"
								onClick={() => {
									setOpen(false);
									onSignOut();
								}}
							>
								<LogOut size={16} />
								<span>Sign Out</span>
							</button>
						</SheetContent>
					</Sheet>
				) : (
					<DropdownMenu open={open} onOpenChange={setOpen}>
						<DropdownMenuTrigger
							render={
								<SidebarMenuButton
									size="lg"
									className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
								/>
							}
						>
							{triggerContent}
						</DropdownMenuTrigger>

						<DropdownMenuContent
							className="w-fit min-w-64 max-w-[calc(100vw-1rem)] rounded-lg border-border/70 p-1"
							side="right"
							align="end"
							sideOffset={4}
						>
							{userInfoPanel}

							<DropdownMenuSeparator />
							<DropdownMenuGroup>
								<DropdownMenuItem
									variant="destructive"
									className="rounded-md text-destructive data-highlighted:bg-destructive data-highlighted:text-destructive-foreground data-highlighted:*:[svg]:!text-destructive-foreground"
									onClick={onSignOut}
								>
									<LogOut size={16} />
									<span>Sign Out</span>
								</DropdownMenuItem>
							</DropdownMenuGroup>
						</DropdownMenuContent>
					</DropdownMenu>
				)}
			</SidebarMenuItem>
		</SidebarMenu>
	);
}
