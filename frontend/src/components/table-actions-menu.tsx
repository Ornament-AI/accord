import { MoreVertical } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type TableAction = {
	label: string;
	onSelect?: () => void;
	variant?: "default" | "destructive";
	disabled?: boolean;
};

interface TableActionsMenuProps {
	label: string;
	actions: readonly TableAction[];
}

export function TableActionsMenu({ label, actions }: TableActionsMenuProps) {
	const visibleActions = actions.filter(Boolean);

	if (visibleActions.length === 0) return null;

	return (
		<DropdownMenu>
			<DropdownMenuTrigger
				render={
					<Button
						type="button"
						variant="ghost"
						size="icon-sm"
						onClick={(event) => event.stopPropagation()}
					/>
				}
			>
				<MoreVertical />
				<span className="sr-only">Actions for {label}</span>
			</DropdownMenuTrigger>
			<DropdownMenuContent align="end">
				{visibleActions.map((action) => (
					<DropdownMenuItem
						key={action.label}
						variant={action.variant === "destructive" ? "destructive" : undefined}
						disabled={action.disabled}
						onClick={(event) => {
							event.stopPropagation();
							action.onSelect?.();
						}}
					>
						{action.label}
					</DropdownMenuItem>
				))}
			</DropdownMenuContent>
		</DropdownMenu>
	);
}
