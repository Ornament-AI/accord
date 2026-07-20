import type { Icon as PhosphorIcon } from "@phosphor-icons/react";
import { BuildingsIcon as Building2 } from "@phosphor-icons/react/dist/csr/Buildings";
import { ChartBarIcon as FileBarChart2 } from "@phosphor-icons/react/dist/csr/ChartBar";
import { ClipboardTextIcon as ClipboardList } from "@phosphor-icons/react/dist/csr/ClipboardText";
import { MoneyIcon as Banknote } from "@phosphor-icons/react/dist/csr/Money";
import { WalletIcon as WalletCards } from "@phosphor-icons/react/dist/csr/Wallet";

import type { Capability } from "@/types/auth";

export type NavRegistryChild = {
	title: string;
	path: string;
	/** When set, the child is shown only if `hasCapability(capability)` is true. */
	capability?: Capability;
};

export type NavRegistryEntry = {
	title: string;
	icon: PhosphorIcon;
	path: string;
	/** When set, the item is shown only if `hasCapability(capability)` is true. */
	capability?: Capability;
	children?: readonly NavRegistryChild[];
};

/** Ordered primary navigation using the most direct capability from the frozen contract. */
export const NAV_REGISTRY: readonly NavRegistryEntry[] = [
	{
		title: "Organization",
		icon: Building2,
		path: "/organization",
		capability: "view_master_data",
		children: [
			{ title: "Employees", path: "/employees" },
			{ title: "Offices", path: "/organization/offices" },
			{ title: "Posts", path: "/organization/posts" },
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
