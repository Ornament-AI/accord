import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { LightRays } from "@/components/ui/light-rays";
import { ThemeSwitcher } from "@/components/ui/theme-switcher";
import { useAuth } from "@/contexts/AuthContext";
import { APP_NAME } from "@/lib/branding";

export default function DeploymentNotReadyPage() {
	const { user, logout } = useAuth();

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
		<div className="relative flex min-h-svh flex-col items-center justify-center overflow-hidden bg-background px-6 py-16">
			<LightRays className="opacity-40" />
			<div className="absolute right-4 top-4 z-10">
				<ThemeSwitcher />
			</div>
			<div className="relative z-10 w-full max-w-md space-y-6 text-center">
				<p className="text-sm text-muted-foreground">{APP_NAME}</p>
				<h1
					className="text-2xl font-semibold tracking-tight"
					data-testid="deployment-not-ready-page"
				>
					Deployment Not Ready
				</h1>
				<p className="text-sm text-muted-foreground">
					{user?.email ? (
						<>
							Signed in as <span className="text-foreground">{user.email}</span>.{" "}
						</>
					) : null}
					An operator must bootstrap the organization with{" "}
					<code className="rounded bg-muted px-1 py-0.5 text-xs">
						scripts/provision_organization.py
					</code>{" "}
					before anyone can use {APP_NAME}.
				</p>
				<Button type="button" variant="outline" onClick={() => void handleSignOut()}>
					Sign Out
				</Button>
			</div>
		</div>
	);
}
