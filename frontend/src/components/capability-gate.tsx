import { ShieldSlashIcon as ShieldOff } from "@phosphor-icons/react/dist/csr/ShieldSlash";
import type { ReactNode } from "react";

import { AppLayout } from "@/components/app-layout";
import { EmptyState } from "@/components/empty-state";
import { useAuth } from "@/contexts/AuthContext";
import type { Capability } from "@/types/auth";

type CapabilityGateProps = {
	/** Single capability required to view the page. Ignored when `anyOf` is set. */
	capability?: Capability;
	/** Any-of capability union required to view the page (e.g. pay-run reads). */
	anyOf?: readonly Capability[];
	title?: string;
	children: ReactNode;
};

/**
 * Renders children when the active organization grants `capability` (or any of
 * `anyOf`). Direct URL access without it shows an access-denied empty state
 * (no hard redirect).
 */
export function CapabilityGate({
	capability,
	anyOf,
	title = "Access denied",
	children,
}: CapabilityGateProps) {
	const { hasCapability, hasAnyCapability } = useAuth();

	const allowed = anyOf
		? hasAnyCapability(anyOf)
		: capability === undefined || hasCapability(capability);

	if (!allowed) {
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
