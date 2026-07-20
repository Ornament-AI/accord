import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { LightRays } from "@/components/ui/light-rays";
import { ThemeSwitcher } from "@/components/ui/theme-switcher";
import { useAuth } from "@/contexts/AuthContext";
import { resolveApiUrl } from "@/lib/api-url";
import { APP_NAME } from "@/lib/branding";
import { sanitizeReturnTo } from "@/lib/return-to";

function consumeStoredError(): string | null {
	const stored = sessionStorage.getItem("auth_error");
	if (stored) sessionStorage.removeItem("auth_error");
	return stored;
}

function messageForAuthErrorCode(code: string): string {
	if (code === "auth_failed") {
		return "Sign-in failed. Please try again.";
	}
	return `Unable to sign in (${code}). Please try again.`;
}

function resolveLoginError(urlError: string | null, storedError: string | null): string | null {
	if (urlError) {
		return messageForAuthErrorCode(urlError);
	}
	return storedError;
}

export default function LoginPage() {
	const { user, isLoading } = useAuth();
	const navigate = useNavigate();
	const [searchParams] = useSearchParams();
	const returnTo = sanitizeReturnTo(searchParams.get("returnTo"));
	const urlError = searchParams.get("error");
	const [authError] = useState(() => resolveLoginError(urlError, consumeStoredError()));

	useEffect(() => {
		if (!isLoading && user) {
			navigate(returnTo, { replace: true });
		}
	}, [user, isLoading, navigate, returnTo]);

	const handleSignIn = () => {
		const loginUrl = `${resolveApiUrl("/api/auth/login")}?return_to=${encodeURIComponent(returnTo)}`;
		window.location.assign(loginUrl);
	};

	return (
		<div className="relative flex min-h-svh flex-col items-center justify-center gap-6 overflow-hidden bg-background p-6 md:p-10 [--ray-color:oklch(0.704_0.14_182.503/0.12)] dark:[--ray-color:oklch(0.47_0.076_188.216/0.10)]">
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
							Sign in to continue to your payroll workspace.
						</p>
					</div>

					{authError ? (
						<Alert variant="destructive">
							<AlertDescription>{authError}</AlertDescription>
						</Alert>
					) : null}

					<Button type="button" className="w-full" onClick={handleSignIn}>
						Sign In
					</Button>
				</div>
			</div>
		</div>
	);
}
