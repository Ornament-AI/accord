import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { buildAuthMe, buildRoleAuthMe, ROLE_CAPABILITIES } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { openBaseUiSelect, pickBaseUiOption } from "@/test/helpers";
import { server } from "@/test/msw-server";
import { renderApp } from "@/test/render-app";
import type { Capability } from "@/types/auth";

import { CreateEmployeeDialog } from "./CreateEmployeeDialog";
import { buildEmployeeDetail, createEmployeeHandlers } from "./employee-handlers";
import { ScheduleChangeDialog } from "./ScheduleChangeDialog";

// Warm the same modules the router lazy-loads so Suspense does not stall tests.
import "@/pages/employees/EmployeeListPage";
import "@/pages/employees/EmployeeDetailPage";

const PAGE_TIMEOUT = 15_000;

function renderCreateDialog(open = true) {
	const onOpenChange = vi.fn();
	render(
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<MemoryRouter>
						<CreateEmployeeDialog open={open} onOpenChange={onOpenChange} />
					</MemoryRouter>
				</AuthProvider>
			</ThemeProvider>
		</QueryClientProvider>,
	);
	return { onOpenChange };
}

describe("Employee list page", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"renders employees and supports search and pagination",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: employeeHandlers } = createEmployeeHandlers({ pageSize: 20 });
			server.use(...authHandlers, ...employeeHandlers);

			renderApp({ initialEntries: ["/employees"] });

			expect(
				await screen.findByLabelText("Search employees", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(await screen.findByText("E-001", {}, { timeout: PAGE_TIMEOUT })).toBeInTheDocument();
			expect(screen.getByText("Alice Example")).toBeInTheDocument();
			expect(screen.getAllByText("GPF").length).toBeGreaterThan(0);

			fireEvent.change(screen.getByLabelText("Search employees"), {
				target: { value: "Alice" },
			});

			await waitFor(() => {
				expect(screen.getByText("Alice Example")).toBeInTheDocument();
				expect(screen.queryByText("E-002")).not.toBeInTheDocument();
			});

			fireEvent.change(screen.getByLabelText("Search employees"), {
				target: { value: "" },
			});

			await waitFor(() => {
				expect(screen.getByText("E-002")).toBeInTheDocument();
			});

			fireEvent.click(screen.getByRole("button", { name: "Go to page 2" }));

			await waitFor(() => {
				expect(screen.getByText("E-021")).toBeInTheDocument();
				expect(screen.queryByText("E-001")).not.toBeInTheDocument();
			});
		},
		PAGE_TIMEOUT,
	);

	it(
		"gates New employee on manage_master_data",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("auditor"),
			});
			const { handlers: employeeHandlers } = createEmployeeHandlers();
			server.use(...authHandlers, ...employeeHandlers);

			renderApp({ initialEntries: ["/employees"] });

			expect(await screen.findByText("E-001", {}, { timeout: PAGE_TIMEOUT })).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /New employee/i })).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});

describe("Employee detail page", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"shows masked sensitive fields by default",
		async () => {
			const detail = buildEmployeeDetail({
				id: "emp-1",
				employee_number: "E-001",
			});
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const { handlers: employeeHandlers } = createEmployeeHandlers({
				employees: [
					{
						id: "emp-1",
						employee_number: "E-001",
						name: "Alice Example",
						sevarth_id: "SEV-001",
						retirement_regime: "gpf",
					},
				],
				details: { "emp-1": detail },
			});
			server.use(...authHandlers, ...employeeHandlers);

			renderApp({ initialEntries: ["/employees/emp-1"] });

			expect(
				await screen.findByTestId("employee-detail-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(await screen.findByText("••••234F")).toBeInTheDocument();
			expect(screen.queryByText("ABCDE1234F")).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"shows reveal toggle only when reveal_sensitive_fields is granted",
		async () => {
			const withRevealCaps = buildAuthMe({
				active_organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
					role: "organization_administrator",
					capabilities: ROLE_CAPABILITIES.organization_administrator,
				},
			});
			const withoutReveal = buildAuthMe({
				active_organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
					role: "payroll_preparer",
					capabilities: ROLE_CAPABILITIES.payroll_preparer.filter(
						(cap): cap is Capability => cap !== "reveal_sensitive_fields",
					),
				},
			});

			const detail = buildEmployeeDetail({ id: "emp-1", employee_number: "E-001" });
			const { handlers: employeeHandlers } = createEmployeeHandlers({
				employees: [
					{
						id: "emp-1",
						employee_number: "E-001",
						name: "Alice Example",
						sevarth_id: "SEV-001",
						retirement_regime: "gpf",
					},
				],
				details: { "emp-1": detail },
			});

			const { handlers: authWithReveal } = createAuthHandlers({ me: withRevealCaps });
			server.use(...authWithReveal, ...employeeHandlers);
			const { unmount } = renderApp({ initialEntries: ["/employees/emp-1"] });
			expect(
				await screen.findByRole(
					"button",
					{ name: /Reveal sensitive fields/i },
					{ timeout: PAGE_TIMEOUT },
				),
			).toBeInTheDocument();
			unmount();
			queryClient.clear();

			const { handlers: authWithoutReveal } = createAuthHandlers({ me: withoutReveal });
			server.use(...authWithoutReveal, ...employeeHandlers);
			renderApp({ initialEntries: ["/employees/emp-1"] });
			expect(
				await screen.findByTestId("employee-detail-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(
				screen.queryByRole("button", { name: /Reveal sensitive fields/i }),
			).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});

describe("CreateEmployeeDialog", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it("requires gpf_jurisdiction when regime is GPF and surfaces 409 on duplicate number", async () => {
		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: employeeHandlers } = createEmployeeHandlers({
			createError: {
				status: 409,
				body: { detail: "Employee number already exists", error: "ConflictError" },
			},
		});
		server.use(...authHandlers, ...employeeHandlers);

		renderCreateDialog();
		await screen.findByRole("heading", { name: "New employee" });

		fireEvent.change(screen.getByLabelText("Employee number"), {
			target: { value: "E-DUP" },
		});
		fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Bob" } });
		fireEvent.change(screen.getByLabelText("Sevarth ID"), { target: { value: "SEV-9" } });
		fireEvent.change(screen.getByLabelText("Date of birth"), {
			target: { value: "1990-01-01" },
		});
		fireEvent.change(screen.getByLabelText("Date of joining"), {
			target: { value: "2015-01-01" },
		});

		openBaseUiSelect(screen.getByLabelText("Retirement regime"));
		pickBaseUiOption("GPF");

		await waitFor(() => {
			expect(screen.getByLabelText("GPF jurisdiction")).toBeInTheDocument();
		});

		fireEvent.click(screen.getByRole("button", { name: "Create employee" }));
		expect(
			await screen.findByText("GPF jurisdiction is required when regime is GPF"),
		).toBeInTheDocument();

		openBaseUiSelect(screen.getByLabelText("GPF jurisdiction"));
		pickBaseUiOption("Mumbai");

		fireEvent.click(screen.getByRole("button", { name: "Create employee" }));
		expect(await screen.findByText("This employee number is already in use")).toBeInTheDocument();
	});
});

describe("ScheduleChangeDialog", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it("surfaces 409 overlap errors inline", async () => {
		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: employeeHandlers } = createEmployeeHandlers({
			versionError: {
				status: 409,
				body: { detail: "Version periods overlap.", error: "ConflictError" },
			},
		});
		server.use(...authHandlers, ...employeeHandlers);

		const profile = buildEmployeeDetail({
			id: "emp-1",
			employee_number: "E-001",
		}).profile;

		render(
			<QueryClientProvider client={queryClient}>
				<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
					<AuthProvider>
						<ScheduleChangeDialog
							open
							onOpenChange={vi.fn()}
							employeeId="emp-1"
							kind="profile"
							activeProfile={profile}
						/>
					</AuthProvider>
				</ThemeProvider>
			</QueryClientProvider>,
		);

		expect(
			await screen.findByRole("heading", { name: /Schedule profile change/i }),
		).toBeInTheDocument();
		fireEvent.click(screen.getByRole("button", { name: "Schedule change" }));

		expect(await screen.findByRole("alert")).toHaveTextContent("Version periods overlap.");
	});
});

describe("Employees capability gate", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"denies direct URL access without view_master_data",
		async () => {
			const me = buildAuthMe({
				active_organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
					role: "report_releaser",
					capabilities: ROLE_CAPABILITIES.report_releaser,
				},
			});
			const { handlers } = createAuthHandlers({ me });
			server.use(...handlers);

			renderApp({ initialEntries: ["/employees"] });

			expect(
				await screen.findByText("You don't have access", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});
