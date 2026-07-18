import { WalletCards } from "lucide-react";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { EmptyState } from "@/components/empty-state";

export default function PayRunsPage() {
	return (
		<CapabilityGate capability="create_run" title="Pay Runs">
			<AppLayout title="Pay Runs">
				<div className="flex min-h-0 flex-1 flex-col p-6">
					<EmptyState
						icon={WalletCards}
						title="Pay runs coming soon"
						description="Payroll run creation and processing will appear here in a future release."
					/>
				</div>
			</AppLayout>
		</CapabilityGate>
	);
}
