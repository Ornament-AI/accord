import type { ReactNode } from "react";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";

interface SiteHeaderProps {
	title: ReactNode;
	actions?: ReactNode;
}

export function SiteHeader({ title, actions }: SiteHeaderProps) {
	const isPrimitiveTitle = typeof title === "string" || typeof title === "number";

	return (
		<header className="flex h-auto min-h-(--header-height) shrink-0 items-center gap-2 border-b transition-[width,height] ease-linear group-has-data-[collapsible=icon]/sidebar-wrapper:min-h-(--header-height)">
			<div className="flex w-full min-w-0 items-center gap-2 px-4 py-3 sm:py-2 lg:px-6">
				<SidebarTrigger className="relative shrink-0 after:absolute after:-inset-2 after:content-[''] sm:-ml-1 sm:after:hidden" />
				<Separator orientation="vertical" className="data-[orientation=vertical]:h-4" />
				<div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden text-sm font-medium [&>*]:min-w-0">
					{isPrimitiveTitle ? <span className="truncate">{title}</span> : title}
				</div>
				{actions ? (
					<div className="ml-2 flex shrink-0 flex-wrap items-center justify-end gap-2">
						{actions}
					</div>
				) : null}
			</div>
		</header>
	);
}
