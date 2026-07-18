import { LayoutDashboard } from "lucide-react";

import { AppLayout } from "@/components/app-layout";
import { EmptyState } from "@/components/empty-state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function DashboardPage() {
	return (
		<AppLayout title="Dashboard">
			<div className="flex min-h-0 flex-1 flex-col gap-6 p-6">
				<Card className="app-material-level-1 app-border-level-1">
					<CardHeader>
						<CardTitle>Payroll workspace</CardTitle>
						<CardDescription>
							Accord shell is ready. Payroll features will appear here as they are implemented.
						</CardDescription>
					</CardHeader>
					<CardContent>
						<EmptyState
							icon={LayoutDashboard}
							title="No payroll data yet"
							description="Connect authentication and backend services to start managing payroll records."
						/>
					</CardContent>
				</Card>
			</div>
		</AppLayout>
	);
}
