import { ClipboardList } from "lucide-react";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { EmptyState } from "@/components/empty-state";

export default function AuditPage() {
	return (
		<CapabilityGate capability="view_audit" title="Audit">
			<AppLayout title="Audit">
				<div className="flex min-h-0 flex-1 flex-col p-6">
					<EmptyState
						icon={ClipboardList}
						title="Audit coming soon"
						description="Audit trail and compliance views will appear here in a future release."
					/>
				</div>
			</AppLayout>
		</CapabilityGate>
	);
}
