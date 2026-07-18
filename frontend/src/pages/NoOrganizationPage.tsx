import { Building2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { CreateOrganizationDialog } from "@/components/create-organization-dialog";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { LightRays } from "@/components/ui/light-rays";
import { ThemeSwitcher } from "@/components/ui/theme-switcher";
import { useAuth } from "@/contexts/AuthContext";
import { APP_NAME } from "@/lib/branding";

export default function NoOrganizationPage() {
	const { user, logout } = useAuth();
	const [createOpen, setCreateOpen] = useState(false);

	const handleSignOut = async () => {
		try {
			await logout();
		} catch (error) {
			toast.error("Sign out failed", {
				description:
					error instanceof Error
						? error.message
						: "Unable to sign out right now. Please try again.",
			});
		}
	};

	return (
		<div className="relative flex min-h-svh flex-col items-center justify-center gap-6 overflow-hidden bg-white p-6 dark:bg-background md:p-10 [--ray-color:rgba(255,165,60,0.4)] dark:[--ray-color:rgba(255,158,11,0.2)]">
			<LightRays color="var(--ray-color)" count={8} blur={30} speed={12} length="75vh" />
			<div className="absolute top-6 right-6 z-10 flex items-center gap-3">
				<span className="text-sm text-muted-foreground">{user?.email}</span>
				<Button type="button" variant="ghost" size="sm" onClick={() => void handleSignOut()}>
					Sign out
				</Button>
				<ThemeSwitcher />
			</div>

			<div className="relative z-10 flex w-full max-w-lg flex-col items-center gap-6">
				<span className="text-base font-medium tracking-tight text-foreground">{APP_NAME}</span>
				<div className="app-material-level-1 flex w-full flex-col gap-6 rounded-lg border app-border-level-1 bg-card p-6">
					<EmptyState
						icon={Building2}
						title="Create your first organization"
						description="You are signed in, but you do not belong to an organization yet. Create one to start using Accord."
					>
						<Button type="button" onClick={() => setCreateOpen(true)}>
							Create organization
						</Button>
					</EmptyState>
				</div>
			</div>

			<CreateOrganizationDialog open={createOpen} onOpenChange={setCreateOpen} />
		</div>
	);
}
