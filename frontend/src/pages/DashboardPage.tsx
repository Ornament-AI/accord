import { AppLayout } from "@/components/app-layout";
import { useAuth } from "@/contexts/AuthContext";

import { DashboardContent } from "./dashboard/DashboardContent";
import { WelcomeCard } from "./dashboard/WelcomeCard";

export default function DashboardPage() {
	const { hasCapability, user, activeOrganization } = useAuth();

	// Dashboard route renders for any authenticated org member. Fetch /api/dashboard
	// only when the org grants view_master_data; without it, show a welcome-only limited state.
	const canViewDashboardData = hasCapability("view_master_data");

	return (
		<AppLayout title="Dashboard">
			<div className="flex min-h-0 flex-1 flex-col gap-6 p-6" data-testid="dashboard-page">
				{canViewDashboardData ? (
					<DashboardContent />
				) : (
					<WelcomeCard userName={user?.name} organizationName={activeOrganization?.name} limited />
				)}
			</div>
		</AppLayout>
	);
}
