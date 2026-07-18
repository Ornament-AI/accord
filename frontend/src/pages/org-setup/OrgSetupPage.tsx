import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { PageShell } from "@/components/page-shell";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/contexts/AuthContext";

import { EmployeeGroupsTab } from "./EmployeeGroupsTab";
import { OfficesTab } from "./OfficesTab";
import { PayrollUnitsTab } from "./PayrollUnitsTab";
import { PostsTab } from "./PostsTab";
import { SettingsTab } from "./SettingsTab";

export function OrgSetupPage() {
	const { hasCapability } = useAuth();
	const canManageMasterData = hasCapability("manage_master_data");
	const canManageOrganization = hasCapability("manage_organization");

	return (
		<CapabilityGate capability="view_master_data" title="Organization Setup">
			<AppLayout title="Organization Setup">
				<PageShell data-testid="org-setup-page">
					<Tabs defaultValue="offices">
						<TabsList variant="line">
							<TabsTrigger value="offices">Offices</TabsTrigger>
							<TabsTrigger value="payroll-units">Payroll Units</TabsTrigger>
							<TabsTrigger value="posts">Posts</TabsTrigger>
							<TabsTrigger value="employee-groups">Employee Groups</TabsTrigger>
							{canManageOrganization ? <TabsTrigger value="settings">Settings</TabsTrigger> : null}
						</TabsList>

						<TabsContent value="offices">
							<OfficesTab canManage={canManageMasterData} />
						</TabsContent>
						<TabsContent value="payroll-units">
							<PayrollUnitsTab canManage={canManageMasterData} />
						</TabsContent>
						<TabsContent value="posts">
							<PostsTab canManage={canManageMasterData} />
						</TabsContent>
						<TabsContent value="employee-groups">
							<EmployeeGroupsTab canManage={canManageMasterData} />
						</TabsContent>
						{canManageOrganization ? (
							<TabsContent value="settings">
								<SettingsTab />
							</TabsContent>
						) : null}
					</Tabs>
				</PageShell>
			</AppLayout>
		</CapabilityGate>
	);
}

export default OrgSetupPage;
