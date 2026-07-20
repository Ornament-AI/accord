import { GrainGradient } from "@paper-design/shaders-react";
import { type FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ThemeSwitcher } from "@/components/ui/theme-switcher";
import { useAuth } from "@/contexts/AuthContext";
import { loginWithMagicCode, loginWithPassword, requestMagicCode } from "@/lib/api/auth";
import { resolveApiUrl } from "@/lib/api-url";
import { APP_NAME } from "@/lib/branding";
import { ApiError } from "@/lib/errors";
import { useReducedMotion } from "@/lib/motion";
import { sanitizeReturnTo } from "@/lib/return-to";
import { useTheme } from "@/lib/ui/providers/theme-provider";

const GRAIN_GRADIENT_COLORS = {
	light: {
		background: "#f6f8f7",
		colors: ["#e7f0ed", "#bddbd4", "#78b9ad", "#2f8179"],
	},
	dark: {
		background: "#121716",
		colors: ["#123331", "#1f5a55", "#2f8179", "#6aa99f"],
	},
};

function useResolvedDarkTheme() {
	const { theme } = useTheme();
	const [systemPrefersDark, setSystemPrefersDark] = useState(() =>
		typeof window !== "undefined" && window.matchMedia
			? window.matchMedia("(prefers-color-scheme: dark)").matches
			: false,
	);

	useEffect(() => {
		if (theme !== "system") return;
		if (typeof window === "undefined" || !window.matchMedia) return;

		const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
		const handleChange = () => setSystemPrefersDark(mediaQuery.matches);
		handleChange();
		mediaQuery.addEventListener("change", handleChange);
		return () => mediaQuery.removeEventListener("change", handleChange);
	}, [theme]);

	return theme === "dark" || (theme === "system" && systemPrefersDark);
}

function LoginBackground() {
	const isDark = useResolvedDarkTheme();
	const prefersReducedMotion = useReducedMotion();
	const palette = isDark ? GRAIN_GRADIENT_COLORS.dark : GRAIN_GRADIENT_COLORS.light;

	return (
		<GrainGradient
			aria-hidden="true"
			className="pointer-events-none absolute inset-0"
			width="100%"
			height="100%"
			colorBack={palette.background}
			colors={palette.colors}
			speed={prefersReducedMotion ? 0 : 1}
		/>
	);
}

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
	const [authError, setAuthError] = useState(() =>
		resolveLoginError(urlError, consumeStoredError()),
	);
	const [step, setStep] = useState<"password" | "request-code" | "verify-code">("password");
	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [code, setCode] = useState("");
	const [isSubmitting, setIsSubmitting] = useState(false);

	useEffect(() => {
		if (!isLoading && user) {
			navigate(returnTo, { replace: true });
		}
	}, [user, isLoading, navigate, returnTo]);

	const completeSignIn = () => window.location.assign(returnTo);

	const handleSignIn = async (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		setAuthError(null);
		setIsSubmitting(true);
		try {
			if (step === "password") {
				await loginWithPassword({ email, password });
				completeSignIn();
			} else if (step === "request-code") {
				await requestMagicCode({ email });
				setStep("verify-code");
			} else {
				await loginWithMagicCode({ email, code });
				completeSignIn();
			}
		} catch (error) {
			if (error instanceof ApiError && error.code === "AuthChallengeRequired") {
				const fallbackUrl = `${resolveApiUrl("/api/auth/login")}?return_to=${encodeURIComponent(returnTo)}`;
				window.location.assign(fallbackUrl);
				return;
			}
			setAuthError(error instanceof Error ? error.message : "Sign-in failed. Please try again.");
		} finally {
			setIsSubmitting(false);
		}
	};

	const switchStep = (nextStep: "password" | "request-code") => {
		setStep(nextStep);
		setAuthError(null);
		setCode("");
	};

	const submitLabel = isSubmitting
		? step === "password"
			? "Signing in…"
			: "Please wait…"
		: step === "request-code"
			? "Send code"
			: "Sign In";

	return (
		<div className="relative flex min-h-svh flex-col items-center justify-center gap-6 overflow-hidden bg-background p-6 md:p-10">
			<LoginBackground />
			<div className="absolute top-6 right-6 z-10">
				<ThemeSwitcher />
			</div>
			<div className="relative z-10 flex w-full max-w-sm flex-col gap-6">
				<div className="flex items-center gap-2 self-center font-medium">
					<span className="whitespace-nowrap text-base font-medium tracking-tight text-foreground">
						{APP_NAME}
					</span>
				</div>

				<div className="flex flex-col gap-6 rounded-lg border app-border-level-1 bg-card p-6 shadow-sm">
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

					<form className="flex flex-col gap-4" onSubmit={handleSignIn}>
						<fieldset
							disabled={isSubmitting}
							className="m-0 flex min-w-0 flex-col gap-4 border-0 p-0"
						>
							<div className="grid gap-2">
								<Label htmlFor="login-email">Email</Label>
								<Input
									id="login-email"
									type="email"
									autoComplete="username"
									autoCapitalize="none"
									value={email}
									onChange={(event) => setEmail(event.target.value)}
									readOnly={step === "verify-code"}
									required
								/>
							</div>
							{step === "password" ? (
								<div className="grid gap-2">
									<Label htmlFor="login-password">Password</Label>
									<Input
										id="login-password"
										type="password"
										autoComplete="current-password"
										value={password}
										onChange={(event) => setPassword(event.target.value)}
										required
									/>
								</div>
							) : null}
							{step === "verify-code" ? (
								<>
									<p className="text-sm text-muted-foreground" role="status">
										Check your email for the one-time sign-in code.
									</p>
									<div className="grid gap-2">
										<Label htmlFor="login-code">Sign-in code</Label>
										<Input
											id="login-code"
											inputMode="numeric"
											autoComplete="one-time-code"
											value={code}
											onChange={(event) => setCode(event.target.value)}
											required
										/>
									</div>
								</>
							) : null}
							<Button type="submit" className="w-full">
								{submitLabel}
							</Button>
						</fieldset>
						<Button
							type="button"
							variant="ghost"
							onClick={() => switchStep(step === "password" ? "request-code" : "password")}
						>
							{step === "password" ? "Email me a sign-in code" : "Use password instead"}
						</Button>
					</form>
				</div>
			</div>
		</div>
	);
}
