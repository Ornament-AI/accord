import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LightRays } from "@/components/ui/light-rays";
import { ThemeSwitcher } from "@/components/ui/theme-switcher";
import { useAuth } from "@/contexts/AuthContext";
import { APP_NAME } from "@/lib/branding";
import { createOrganizationFromName } from "@/lib/create-organization";

export default function NoOrganizationPage() {
	const { user, logout, createOrganization } = useAuth();
	const [name, setName] = useState("");
	const [formError, setFormError] = useState<string | null>(null);
	const [isSubmitting, setIsSubmitting] = useState(false);

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

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setFormError(null);
		setIsSubmitting(true);
		try {
			await createOrganizationFromName(createOrganization, name);
		} catch (error) {
			setFormError(
				error instanceof Error ? error.message : "Unable to create organization right now.",
			);
		} finally {
			setIsSubmitting(false);
		}
	};

	return (
		<div
			data-testid="no-organization-page"
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
				<div className="flex items-center gap-2 self-center font-medium">
					<span className="whitespace-nowrap text-base font-medium tracking-tight text-foreground">
						{APP_NAME}
					</span>
				</div>

				<div className="app-material-level-1 flex flex-col rounded-lg border app-border-level-1 bg-card p-6">
					<form onSubmit={handleSubmit} className="flex flex-col gap-4">
						<div className="grid gap-1.5">
							<Label htmlFor="no-org-name">Organization Name</Label>
							<Input
								id="no-org-name"
								value={name}
								onChange={(event) => setName(event.target.value)}
								placeholder="Acme"
								autoComplete="organization"
								disabled={isSubmitting}
								autoFocus
							/>
						</div>
						{formError ? <p className="text-sm text-destructive">{formError}</p> : null}
						<Button type="submit" className="w-full" disabled={isSubmitting}>
							{isSubmitting ? "Creating…" : "Continue"}
						</Button>
					</form>
				</div>
			</div>
		</div>
	);
}
