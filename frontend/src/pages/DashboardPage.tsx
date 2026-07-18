import { AppLayout } from "@/components/app-layout";
import { PageShell } from "@/components/page-shell";
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
			<PageShell data-testid="dashboard-page">
				{canViewDashboardData ? (
					<DashboardContent />
				) : (
					<WelcomeCard userName={user?.name} organizationName={activeOrganization?.name} limited />
				)}
			</PageShell>
		</AppLayout>
	);
}
