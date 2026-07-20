import { ShieldSlashIcon as ShieldOff } from "@phosphor-icons/react/dist/csr/ShieldSlash";
import type { ReactNode } from "react";

import { AppLayout } from "@/components/app-layout";
import { EmptyState } from "@/components/empty-state";
import { useAuth } from "@/contexts/AuthContext";
import type { Capability } from "@/types/auth";

type CapabilityGateProps = {
	capability: Capability;
	title?: string;
	children: ReactNode;
};

/**
 * Renders children when the active organization grants `capability`.
 * Direct URL access without the capability shows an access-denied empty state
 * (no hard redirect).
 */
export function CapabilityGate({
	capability,
	title = "Access denied",
	children,
}: CapabilityGateProps) {
	const { hasCapability } = useAuth();

	if (!hasCapability(capability)) {
		return (
			<AppLayout title={title}>
				<div className="flex min-h-0 flex-1 flex-col p-6">
					<EmptyState
						icon={ShieldOff}
						title="You Don't Have Access"
						description="Your role in this organization does not include permission to view this page."
					/>
				</div>
			</AppLayout>
		);
	}

	return children;
}
