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

export type NavRegistryChild = {
	title: string;
	path: string;
	/** When set, the child is shown only if `hasCapability(capability)` is true. */
	capability?: Capability;
};

export type NavRegistryEntry = {
	title: string;
	icon: LucideIcon;
	path: string;
	/** When set, the item is shown only if `hasCapability(capability)` is true. */
	capability?: Capability;
	children?: readonly NavRegistryChild[];
};

/**
 * Ordered primary navigation. Dashboard has no capability gate.
 * Other entries use the most direct capability from the frozen contract.
 */
export const NAV_REGISTRY: readonly NavRegistryEntry[] = [
	{ title: "Dashboard", icon: LayoutDashboard, path: "/" },
	{ title: "Employees", icon: Users, path: "/employees", capability: "view_master_data" },
	{
		title: "Organization",
		icon: Building2,
		path: "/organization",
		capability: "view_master_data",
		children: [
			{ title: "Offices", path: "/organization/offices" },
			{ title: "Payroll Units", path: "/organization/payroll-units" },
			{ title: "Posts", path: "/organization/posts" },
			{ title: "Employee Groups", path: "/organization/employee-groups" },
		],
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
