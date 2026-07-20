import { type ReactNode, useState } from "react";
import { Navigate } from "react-router";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { PageShell } from "@/components/page-shell";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";

import { OfficesTab } from "./OfficesTab";
import { PostsTab } from "./PostsTab";

/** Redirect `/organization` → `/organization/offices`. */
export function OrgSetupIndexRedirect() {
	return <Navigate to="offices" replace />;
}

function CatalogAddButton({ onClick }: { onClick: () => void }) {
	return (
		<Button size="xs" onClick={onClick}>
			Add
		</Button>
	);
}

function OrgCatalogPage({
	title,
	testId,
	canManage,
	children,
}: {
	title: string;
	testId: string;
	canManage: boolean;
	children: (controls: {
		createOpen: boolean;
		setCreateOpen: (open: boolean) => void;
	}) => ReactNode;
}) {
	const [createOpen, setCreateOpen] = useState(false);

	return (
		<CapabilityGate capability="view_master_data" title={title}>
			<AppLayout
				title={title}
				actions={canManage ? <CatalogAddButton onClick={() => setCreateOpen(true)} /> : undefined}
			>
				<PageShell data-testid={testId}>{children({ createOpen, setCreateOpen })}</PageShell>
			</AppLayout>
		</CapabilityGate>
	);
}

export function OfficesPage() {
	const { hasCapability } = useAuth();
	const canManage = hasCapability("manage_master_data");
	return (
		<OrgCatalogPage title="Offices" testId="offices-page" canManage={canManage}>
			{({ createOpen, setCreateOpen }) => (
				<OfficesTab
					canManage={canManage}
					createOpen={createOpen}
					onCreateOpenChange={setCreateOpen}
				/>
			)}
		</OrgCatalogPage>
	);
}

export function PostsPage() {
	const { hasCapability } = useAuth();
	const canManage = hasCapability("manage_master_data");
	return (
		<OrgCatalogPage title="Posts" testId="posts-page" canManage={canManage}>
			{({ createOpen, setCreateOpen }) => (
				<PostsTab
					canManage={canManage}
					createOpen={createOpen}
					onCreateOpenChange={setCreateOpen}
				/>
			)}
		</OrgCatalogPage>
	);
}

export default OfficesPage;
