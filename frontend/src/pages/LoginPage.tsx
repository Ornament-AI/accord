import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { LightRays } from "@/components/ui/light-rays";
import { ThemeSwitcher } from "@/components/ui/theme-switcher";
import { useAuth } from "@/contexts/AuthContext";
import { APP_NAME } from "@/lib/branding";

function consumeStoredError(): string | null {
	const stored = sessionStorage.getItem("auth_error");
	if (stored) sessionStorage.removeItem("auth_error");
	return stored;
}

export default function LoginPage() {
	const { user, isLoading } = useAuth();
	const navigate = useNavigate();
	const [searchParams] = useSearchParams();
	const returnTo = searchParams.get("returnTo") || "/";
	const [authError] = useState(consumeStoredError);

	useEffect(() => {
		if (!isLoading && user) {
			navigate(returnTo, { replace: true });
		}
	}, [user, isLoading, navigate, returnTo]);

	return (
		<div className="relative flex min-h-svh flex-col items-center justify-center gap-6 overflow-hidden bg-white p-6 dark:bg-background md:p-10 [--ray-color:rgba(255,165,60,0.4)] dark:[--ray-color:rgba(255,158,11,0.2)]">
			<LightRays color="var(--ray-color)" count={8} blur={30} speed={12} length="75vh" />
			<div className="absolute top-6 right-6 z-10">
				<ThemeSwitcher />
			</div>
			<div className="relative z-10 flex w-full max-w-sm flex-col gap-6">
				<div className="flex items-center gap-2 self-center font-medium">
					<span className="whitespace-nowrap text-base font-medium tracking-tight text-foreground">
						{APP_NAME}
					</span>
				</div>

				<div className="app-material-level-1 flex flex-col gap-6 rounded-lg border app-border-level-1 bg-card p-6">
					<div className="flex flex-col items-center gap-2 text-center">
						<h1 className="text-2xl font-semibold">Welcome</h1>
						<p className="text-sm text-muted-foreground">
							Sign-in will be available once authentication is configured.
						</p>
					</div>

					{authError ? (
						<Alert variant="destructive">
							<AlertDescription>{authError}</AlertDescription>
						</Alert>
					) : null}

					<Button type="button" className="w-full" disabled>
						Sign in
					</Button>
				</div>
			</div>
		</div>
	);
}
