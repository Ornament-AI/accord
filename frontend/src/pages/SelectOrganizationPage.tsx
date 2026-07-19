import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { LightRays } from "@/components/ui/light-rays";
import { ThemeSwitcher } from "@/components/ui/theme-switcher";
import { useAuth } from "@/contexts/AuthContext";
import { APP_NAME } from "@/lib/branding";

export default function SelectOrganizationPage() {
	const { user, organizations, switchOrganization, logout } = useAuth();
	const [switchingId, setSwitchingId] = useState<string | null>(null);
	const [switchError, setSwitchError] = useState<string | null>(null);

	const handleSwitch = async (organizationId: string) => {
		if (switchingId) return;
		setSwitchError(null);
		setSwitchingId(organizationId);
		try {
			await switchOrganization(organizationId);
		} catch (error) {
			setSwitchError(
				error instanceof Error ? error.message : "Unable to switch organization right now.",
			);
			setSwitchingId(null);
		}
	};

	const handleSignOut = async () => {
		try {
			await logout();
		} catch (error) {
			toast.error("Sign out failed", {
				description: error instanceof Error ? error.message : "Please try again.",
			});
		}
	};

	return (
		<div
			data-testid="organization-selection-page"
			className="relative flex min-h-svh flex-col items-center justify-center gap-6 overflow-hidden bg-background p-6 md:p-10 [--ray-color:oklch(0.704_0.14_182.503/0.12)] dark:[--ray-color:oklch(0.47_0.076_188.216/0.10)]"
		>
			<LightRays color="var(--ray-color)" count={8} blur={30} speed={12} length="75vh" />
			<div className="absolute top-6 left-6 z-20 flex items-center gap-2">
				<span
					className="flex h-8 max-w-[min(100vw-12rem,18rem)] items-center truncate rounded-full border app-border-level-1 bg-card/90 px-3 text-sm leading-none text-muted-foreground shadow-sm backdrop-blur-sm"
					title={user?.email}
				>
					{user?.email}
				</span>
				<Button
					type="button"
					variant="outline"
					size="sm"
					className="h-8 rounded-full border app-border-level-1 bg-card/90 px-3 text-sm font-normal leading-none text-muted-foreground shadow-sm backdrop-blur-sm hover:border-destructive/40 hover:bg-destructive/10 hover:text-destructive dark:bg-card/90 dark:hover:bg-destructive/15 dark:hover:text-destructive"
					onClick={() => void handleSignOut()}
				>
					Sign Out
				</Button>
			</div>
			<div className="absolute top-6 right-6 z-20">
				<ThemeSwitcher />
			</div>

			<div className="relative z-10 flex w-full max-w-sm flex-col gap-6">
				<div className="self-center text-base font-medium tracking-tight text-foreground">
					{APP_NAME}
				</div>
				<div className="app-material-level-1 flex flex-col gap-4 rounded-lg border app-border-level-1 bg-card p-6">
					<div className="flex flex-col gap-1 text-center">
						<h1 className="text-xl font-semibold">Select an organization</h1>
						<p className="text-sm text-muted-foreground">
							Choose the payroll workspace you want to open.
						</p>
					</div>
					<div className="flex flex-col gap-2" aria-busy={switchingId !== null}>
						{organizations.map((organization) => (
							<Button
								key={organization.id}
								type="button"
								variant="outline"
								className="h-auto min-h-10 justify-start whitespace-normal py-2 text-left"
								disabled={switchingId !== null}
								onClick={() => void handleSwitch(organization.id)}
							>
								<span className="flex min-w-0 flex-col items-start">
									<span className="max-w-full truncate">
										{switchingId === organization.id ? "Opening…" : organization.name}
									</span>
									<span className="max-w-full truncate text-xs font-normal text-muted-foreground">
										{organization.slug}
									</span>
								</span>
							</Button>
						))}
					</div>
					{switchError ? (
						<p role="alert" className="text-sm text-destructive">
							{switchError}
						</p>
					) : null}
				</div>
			</div>
		</div>
	);
}
