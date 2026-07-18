import { LayoutDashboard } from "lucide-react";

import { AppLayout } from "@/components/app-layout";
import { EmptyState } from "@/components/empty-state";
import { PageShell } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { useAuth } from "@/contexts/AuthContext";

import { DashboardContent } from "./dashboard/DashboardContent";

export default function DashboardPage() {
	const { hasCapability } = useAuth();

	// Dashboard route renders for any authenticated org member. Fetch /api/dashboard
	// only when the org grants view_master_data; without it, show a limited empty state.
	const canViewDashboardData = hasCapability("view_master_data");

	return (
		<AppLayout title="Dashboard">
			<PageShell data-testid="dashboard-page">
				{canViewDashboardData ? (
					<DashboardContent />
				) : (
					<Card data-testid="dashboard-limited">
						<CardContent className="pt-6">
							<EmptyState
								icon={LayoutDashboard}
								title="Limited dashboard access"
								description="You can use Accord, but this organization role does not include permission to view payroll master-data metrics."
							/>
						</CardContent>
					</Card>
				)}
			</PageShell>
		</AppLayout>
	);
}
