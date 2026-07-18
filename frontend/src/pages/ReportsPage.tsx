import { FileBarChart2 } from "lucide-react";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { EmptyState } from "@/components/empty-state";

export default function ReportsPage() {
	return (
		<CapabilityGate capability="generate_reports" title="Reports">
			<AppLayout title="Reports">
				<div className="flex min-h-0 flex-1 flex-col p-6">
					<EmptyState
						icon={FileBarChart2}
						title="Reports coming soon"
						description="Payroll report generation will appear here in a future release."
					/>
				</div>
			</AppLayout>
		</CapabilityGate>
	);
}
