import type { LucideIcon } from "lucide-react";
import {
	Banknote,
	Building2,
	ClipboardList,
	FileBarChart2,
	LayoutDashboard,
	Users,
	WalletCards,
} from "lucide-react";

import type { Capability } from "@/types/auth";

export type NavRegistryEntry = {
	title: string;
	icon: LucideIcon;
	path: string;
	/** When set, the item is shown only if `hasCapability(capability)` is true. */
	capability?: Capability;
};

/**
 * Ordered primary navigation. Dashboard has no capability gate.
 * Other entries use the most direct capability from the frozen contract.
 */
export const NAV_REGISTRY: readonly NavRegistryEntry[] = [
	{ title: "Dashboard", icon: LayoutDashboard, path: "/" },
	{ title: "Employees", icon: Users, path: "/employees", capability: "view_master_data" },
	{
		title: "Organization Setup",
		icon: Building2,
		path: "/organization",
		capability: "manage_organization",
	},
	{
		title: "Pay Components",
		icon: WalletCards,
		path: "/pay-components",
		capability: "view_master_data",
	},
	{ title: "Pay Runs", icon: Banknote, path: "/pay-runs", capability: "create_run" },
	{ title: "Reports", icon: FileBarChart2, path: "/reports", capability: "generate_reports" },
	{ title: "Audit", icon: ClipboardList, path: "/audit", capability: "view_audit" },
] as const;
