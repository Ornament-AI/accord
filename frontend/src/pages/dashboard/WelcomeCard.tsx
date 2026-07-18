import { LayoutDashboard } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { APP_NAME } from "@/lib/branding";

type WelcomeCardProps = {
	userName?: string | null;
	organizationName?: string | null;
	limited?: boolean;
};

export function WelcomeCard({ userName, organizationName, limited = false }: WelcomeCardProps) {
	const greeting = userName?.trim() ? `Welcome, ${userName.trim()}` : `Welcome to ${APP_NAME}`;
	const orgLine = organizationName?.trim()
		? `You're signed in to ${organizationName.trim()}.`
		: "Select an organization to get started.";

	return (
		<Card className="app-material-level-1 app-border-level-1" data-testid="dashboard-welcome">
			<CardHeader>
				<CardTitle>{greeting}</CardTitle>
				<CardDescription>
					{limited
						? `${orgLine} Your role can open the payroll workspace, but detailed dashboard metrics require view access.`
						: `${orgLine} Here's a snapshot of your payroll workspace.`}
				</CardDescription>
			</CardHeader>
			{limited ? (
				<CardContent>
					<EmptyState
						icon={LayoutDashboard}
						title="Limited dashboard access"
						description="You can use Accord, but this organization role does not include permission to view payroll master-data metrics."
					/>
				</CardContent>
			) : null}
		</Card>
	);
}
