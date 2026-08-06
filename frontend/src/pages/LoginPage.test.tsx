import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import LoginPage from "@/pages/LoginPage";
import { createAuthHandlers } from "@/test/auth-handlers";
import { server } from "@/test/msw-server";

vi.mock("@paper-design/shaders-react", () => ({
	GrainGradient: () => <div data-testid="grain-gradient" />,
}));

function renderLogin(path = "/login") {
	return render(
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<MemoryRouter initialEntries={[path]}>
						<Routes>
							<Route path="/login" element={<LoginPage />} />
						</Routes>
					</MemoryRouter>
				</AuthProvider>
			</ThemeProvider>
		</QueryClientProvider>,
	);
}

describe("LoginPage", () => {
	beforeEach(() => {
		queryClient.clear();
		sessionStorage.clear();
	});

	afterEach(() => {
		vi.restoreAllMocks();
		vi.unstubAllGlobals();
	});

	it("signs in with Accord's password form and preserves returnTo", async () => {
		const assignSpy = vi.fn();
		vi.stubGlobal("location", {
			...window.location,
			assign: assignSpy,
			href: "http://localhost/login",
			pathname: "/login",
			search: "",
			hash: "",
		});

		const { handlers } = createAuthHandlers({ unauthenticated: true });
		server.use(
			...handlers,
			http.post("/api/auth/login/password", async ({ request }) => {
				expect(await request.json()).toEqual({
					email: "hello@ornament.systems",
					password: "correct horse battery staple",
				});
				return new HttpResponse(null, { status: 204 });
			}),
		);

		renderLogin("/login?returnTo=%2Fpay-runs");
		fireEvent.change(await screen.findByLabelText("Email"), {
			target: { value: "hello@ornament.systems" },
		});
		fireEvent.change(screen.getByLabelText("Password"), {
			target: { value: "correct horse battery staple" },
		});
		expect(screen.getByTestId("grain-gradient")).toBeInTheDocument();

		fireEvent.click(screen.getByRole("button", { name: "Sign In" }));

		await waitFor(() => {
			expect(assignSpy).toHaveBeenCalledWith("/pay-runs");
		});
	});

	it("requests and submits an email sign-in code without leaving Accord", async () => {
		const assignSpy = vi.fn();
		vi.stubGlobal("location", { ...window.location, assign: assignSpy });
		const { handlers } = createAuthHandlers({ unauthenticated: true });
		server.use(
			...handlers,
			http.post("/api/auth/magic-code", () => new HttpResponse(null, { status: 204 })),
			http.post("/api/auth/login/magic-code", () => new HttpResponse(null, { status: 204 })),
		);

		renderLogin();
		fireEvent.click(await screen.findByRole("button", { name: "Email me a sign-in code" }));
		fireEvent.change(screen.getByLabelText("Email"), {
			target: { value: "hello@ornament.systems" },
		});
		fireEvent.click(screen.getByRole("button", { name: "Send code" }));
		expect(await screen.findByText("Enter the six-digit code sent to your email.")).toBeVisible();
		expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
		fireEvent.change(screen.getByLabelText("Sign-in code"), { target: { value: "123456" } });
		fireEvent.click(screen.getByRole("button", { name: "Sign In" }));

		await waitFor(() => expect(assignSpy).toHaveBeenCalledWith("/"));
	});

	it("keeps an unregistered email on the initial code-request screen", async () => {
		const { handlers } = createAuthHandlers({ unauthenticated: true });
		server.use(
			...handlers,
			http.post("/api/auth/magic-code", () =>
				HttpResponse.json(
					{
						detail: "This email is not registered with us.",
						error: "EmailNotRegistered",
					},
					{ status: 403 },
				),
			),
		);

		renderLogin();
		fireEvent.click(await screen.findByRole("button", { name: "Email me a sign-in code" }));
		fireEvent.change(screen.getByLabelText("Email"), {
			target: { value: "missing@example.com" },
		});
		fireEvent.click(screen.getByRole("button", { name: "Send code" }));

		expect(await screen.findByRole("alert")).toHaveTextContent(
			"This email is not registered with us.",
		);
		expect(screen.getByLabelText("Email")).toHaveValue("missing@example.com");
		expect(screen.queryByLabelText("Sign-in code")).not.toBeInTheDocument();
	});

	it("preserves non-registration 403 errors on the code-request screen", async () => {
		const { handlers } = createAuthHandlers({ unauthenticated: true });
		server.use(
			...handlers,
			http.post("/api/auth/magic-code", () =>
				HttpResponse.json(
					{
						detail: "Sign-in is unavailable for this request.",
						error: "SignInForbidden",
					},
					{ status: 403 },
				),
			),
		);

		renderLogin();
		fireEvent.click(await screen.findByRole("button", { name: "Email me a sign-in code" }));
		fireEvent.change(screen.getByLabelText("Email"), {
			target: { value: "member@example.com" },
		});
		fireEvent.click(screen.getByRole("button", { name: "Send code" }));

		expect(await screen.findByRole("alert")).toHaveTextContent(
			"Sign-in is unavailable for this request.",
		);
		expect(screen.queryByLabelText("Sign-in code")).not.toBeInTheDocument();
	});

	it("uses the safe hosted continuation only when WorkOS requires a challenge", async () => {
		const assignSpy = vi.fn();
		vi.stubGlobal("location", { ...window.location, assign: assignSpy });
		const { handlers } = createAuthHandlers({ unauthenticated: true });
		server.use(
			...handlers,
			http.post("/api/auth/login/password", () =>
				HttpResponse.json(
					{
						detail: "Additional verification is required to finish signing in.",
						error: "AuthChallengeRequired",
					},
					{ status: 409 },
				),
			),
		);

		renderLogin("/login?returnTo=%2Fpay-runs");
		fireEvent.change(await screen.findByLabelText("Email"), {
			target: { value: "hello@ornament.systems" },
		});
		fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
		fireEvent.click(screen.getByRole("button", { name: "Sign In" }));

		await waitFor(() => {
			expect(assignSpy).toHaveBeenCalledWith("/api/auth/login?return_to=%2Fpay-runs");
		});
	});

	it("prefers the URL error param over sessionStorage auth_error", async () => {
		sessionStorage.setItem("auth_error", "Stored session message");
		const { handlers } = createAuthHandlers({ unauthenticated: true });
		server.use(...handlers);

		renderLogin("/login?error=auth_failed");

		expect(await screen.findByText("Sign-in failed. Please try again.")).toBeInTheDocument();
		expect(screen.queryByText("Stored session message")).not.toBeInTheDocument();
	});

	it("surfaces unknown error codes with a debug-friendly message", async () => {
		const { handlers } = createAuthHandlers({ unauthenticated: true });
		server.use(...handlers);

		renderLogin("/login?error=weird_code");

		expect(
			await screen.findByText("Unable to sign in (weird_code). Please try again."),
		).toBeInTheDocument();
	});
});
