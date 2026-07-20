import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { LightRays } from "@/components/ui/light-rays";
import { ThemeSwitcher } from "@/components/ui/theme-switcher";
import { useAuth } from "@/contexts/AuthContext";
import { APP_NAME } from "@/lib/branding";

export default function NotProvisionedPage() {
	const { user, organization, logout } = useAuth();

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
				<h1 className="text-2xl font-semibold tracking-tight" data-testid="not-provisioned-page">
					Access Not Provisioned
				</h1>
				<p className="text-sm text-muted-foreground">
					{user?.email ? (
						<>
							Signed in as <span className="text-foreground">{user.email}</span>.{" "}
						</>
					) : null}
					{organization ? (
						<>
							Ask an administrator of{" "}
							<span className="text-foreground">{organization.name}</span> to invite you.
						</>
					) : (
						<>Ask an administrator to invite you.</>
					)}
				</p>
				<Button type="button" variant="outline" onClick={() => void handleSignOut()}>
					Sign Out
				</Button>
			</div>
		</div>
	);
}
