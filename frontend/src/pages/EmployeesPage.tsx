import { Users } from "lucide-react";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { EmptyState } from "@/components/empty-state";

export default function EmployeesPage() {
	return (
		<CapabilityGate capability="view_master_data" title="Employees">
			<AppLayout title="Employees">
				<div className="flex min-h-0 flex-1 flex-col p-6">
					<EmptyState
						icon={Users}
						title="Employees coming soon"
						description="Employee master data management will appear here in a future release."
					/>
				</div>
			</AppLayout>
		</CapabilityGate>
	);
}
