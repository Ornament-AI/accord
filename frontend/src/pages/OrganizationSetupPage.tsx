import { Building2 } from "lucide-react";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { EmptyState } from "@/components/empty-state";

export default function OrganizationSetupPage() {
	return (
		<CapabilityGate capability="manage_organization" title="Organization Setup">
			<AppLayout title="Organization Setup">
				<div className="flex min-h-0 flex-1 flex-col p-6">
					<EmptyState
						icon={Building2}
						title="Organization setup coming soon"
						description="Organization settings and configuration will appear here in a future release."
					/>
				</div>
			</AppLayout>
		</CapabilityGate>
	);
}
