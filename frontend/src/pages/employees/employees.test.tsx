import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import {
	buildEmployeeGroup,
	buildOffice,
	buildPayrollUnit,
	buildPost,
	createOrgSetupHandlers,
} from "@/pages/org-setup/org-setup-handlers";
import { buildAuthMe, buildRoleAuthMe, ROLE_CAPABILITIES } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { openBaseUiSelect, pickBaseUiOption, pickDateByLabel } from "@/test/helpers";
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

			expect(await screen.findByText("E-001", {}, { timeout: PAGE_TIMEOUT })).toBeInTheDocument();
			expect(screen.getByText("Alice Example")).toBeInTheDocument();
			expect(screen.getAllByText("GPF").length).toBeGreaterThan(0);

			const searchInput = screen.getByRole("textbox", { name: "Search Employees" });
			fireEvent.change(searchInput, { target: { value: "Alice" } });

			await waitFor(() => {
				expect(screen.getByText("Alice Example")).toBeInTheDocument();
				expect(screen.queryByText("E-002")).not.toBeInTheDocument();
			});

			fireEvent.change(searchInput, { target: { value: "" } });

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
		"gates Add employee on manage_master_data",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("payroll_reviewer"),
			});
			const { handlers: employeeHandlers } = createEmployeeHandlers();
			server.use(...authHandlers, ...employeeHandlers);

			renderApp({ initialEntries: ["/employees"] });

			expect(await screen.findByText("E-001", {}, { timeout: PAGE_TIMEOUT })).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /^Add$/i })).not.toBeInTheDocument();
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
		await screen.findByRole("heading", { name: "New Employee" });

		fireEvent.change(screen.getByLabelText("Employee Number"), {
			target: { value: "E-DUP" },
		});
		fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Bob" } });
		fireEvent.change(screen.getByLabelText("Sevarth ID"), { target: { value: "SEV-9" } });
		{
			const now = new Date();
			const dob = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-05`;
			const doj = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-10`;
			pickDateByLabel("Date of Birth", dob);
			pickDateByLabel("Date of Joining", doj);
		}

		openBaseUiSelect(screen.getByLabelText("Retirement Regime"));
		pickBaseUiOption("GPF");

		await waitFor(() => {
			expect(screen.getByLabelText("GPF Jurisdiction")).toBeInTheDocument();
		});

		fireEvent.click(screen.getByRole("button", { name: "Create employee" }));
		expect(
			await screen.findByText("GPF jurisdiction is required when regime is GPF"),
		).toBeInTheDocument();

		openBaseUiSelect(screen.getByLabelText("GPF Jurisdiction"));
		pickBaseUiOption("Mumbai");

		fireEvent.click(screen.getByRole("button", { name: "Create employee" }));
		expect(await screen.findByText("This employee number is already in use")).toBeInTheDocument();
	});

	it("shows named office / payroll unit / post selectors in posting section", async () => {
		const officeId = "db4cb0bd-bd7f-45f7-986a-1acc0846f2f8";
		const payrollUnitId = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";
		const postId = "f9e8d7c6-b5a4-3210-9876-543210fedcba";
		const employeeGroupId = "11223344-5566-7788-99aa-bbccddeeff00";

		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: employeeHandlers } = createEmployeeHandlers();
		const { handlers: orgHandlers } = createOrgSetupHandlers({
			offices: [
				buildOffice({ id: officeId, code: "HO", name: "Head Office" }),
				buildOffice({ id: "office-2", code: "RO", name: "Regional Office" }),
			],
			payrollUnits: [
				buildPayrollUnit({ id: payrollUnitId, code: "PU-HQ", name: "HQ Payroll" }),
				buildPayrollUnit({ id: "pu-2", code: "PU-REG", name: "Regional Payroll" }),
			],
			posts: [
				buildPost({ id: postId, designation: "Clerk", class_name: "Class III" }),
				buildPost({ id: "post-2", designation: "Officer", class_name: "Class I" }),
			],
			employeeGroups: [buildEmployeeGroup({ id: employeeGroupId, code: "GRP-A", name: "Group A" })],
		});
		server.use(...authHandlers, ...employeeHandlers, ...orgHandlers);

		renderCreateDialog();
		await screen.findByRole("heading", { name: "New Employee" });

		fireEvent.click(screen.getByRole("button", { name: "Posting" }));

		expect(screen.getByText("Office")).toBeInTheDocument();
		expect(screen.getByText("Payroll Unit")).toBeInTheDocument();
		expect(screen.getByText("Post")).toBeInTheDocument();
		expect(screen.getByText("Employee Group")).toBeInTheDocument();
		expect(screen.queryByText("Office ID")).not.toBeInTheDocument();
		expect(screen.queryByText("Payroll Unit ID")).not.toBeInTheDocument();
		expect(screen.queryByText("Post ID")).not.toBeInTheDocument();

		expect(await screen.findByRole("combobox", { name: "Office" })).toHaveTextContent(
			"Select office",
		);
		expect(screen.getByRole("combobox", { name: "Payroll Unit" })).toHaveTextContent(
			"Select payroll unit",
		);
		expect(screen.getByRole("combobox", { name: "Post" })).toHaveTextContent("Select post");
		expect(screen.getByRole("combobox", { name: "Employee Group" })).toHaveTextContent("None");

		openBaseUiSelect(screen.getByRole("combobox", { name: "Office" }));
		expect(await screen.findByRole("option", { name: "Head Office" })).toBeInTheDocument();
		expect(screen.getByRole("option", { name: "Regional Office" })).toBeInTheDocument();
		pickBaseUiOption("Head Office");
		await waitFor(() => {
			expect(screen.getByRole("combobox", { name: "Office" })).toHaveTextContent("Head Office");
		});

		openBaseUiSelect(screen.getByRole("combobox", { name: "Payroll Unit" }));
		pickBaseUiOption("HQ Payroll");
		await waitFor(() => {
			expect(screen.getByRole("combobox", { name: "Payroll Unit" })).toHaveTextContent(
				"HQ Payroll",
			);
		});

		openBaseUiSelect(screen.getByRole("combobox", { name: "Post" }));
		pickBaseUiOption("Clerk");
		await waitFor(() => {
			expect(screen.getByRole("combobox", { name: "Post" })).toHaveTextContent("Clerk");
		});

		openBaseUiSelect(screen.getByRole("combobox", { name: "Employee Group" }));
		pickBaseUiOption("Group A");
		await waitFor(() => {
			expect(screen.getByRole("combobox", { name: "Employee Group" })).toHaveTextContent("Group A");
		});
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
		fireEvent.click(screen.getByRole("button", { name: "Submit" }));

		expect(await screen.findByRole("alert")).toHaveTextContent("Version periods overlap.");
	});

	it("shows named office / payroll unit / post selectors for posting changes", async () => {
		const officeId = "db4cb0bd-bd7f-45f7-986a-1acc0846f2f8";
		const payrollUnitId = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";
		const postId = "f9e8d7c6-b5a4-3210-9876-543210fedcba";
		const employeeGroupId = "11223344-5566-7788-99aa-bbccddeeff00";

		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: employeeHandlers } = createEmployeeHandlers();
		const { handlers: orgHandlers } = createOrgSetupHandlers({
			offices: [
				buildOffice({ id: officeId, code: "HO", name: "Head Office" }),
				buildOffice({ id: "office-2", code: "RO", name: "Regional Office" }),
			],
			payrollUnits: [
				buildPayrollUnit({ id: payrollUnitId, code: "PU-HQ", name: "HQ Payroll" }),
				buildPayrollUnit({ id: "pu-2", code: "PU-REG", name: "Regional Payroll" }),
			],
			posts: [
				buildPost({ id: postId, designation: "Clerk", class_name: "Class III" }),
				buildPost({ id: "post-2", designation: "Officer", class_name: "Class I" }),
			],
			employeeGroups: [buildEmployeeGroup({ id: employeeGroupId, code: "GRP-A", name: "Group A" })],
		});
		server.use(...authHandlers, ...employeeHandlers, ...orgHandlers);

		const posting = {
			id: "posting-1",
			effective_from: "2026-01-01",
			effective_to: null,
			office_id: officeId,
			payroll_unit_id: payrollUnitId,
			post_id: postId,
			employee_group_id: employeeGroupId,
			created_at: "2026-01-15T10:00:00Z",
			created_by: "user-1",
			change_reason: null,
		};

		render(
			<QueryClientProvider client={queryClient}>
				<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
					<AuthProvider>
						<ScheduleChangeDialog
							open
							onOpenChange={vi.fn()}
							employeeId="emp-1"
							kind="posting"
							activePosting={posting}
						/>
					</AuthProvider>
				</ThemeProvider>
			</QueryClientProvider>,
		);

		expect(
			await screen.findByRole("heading", { name: /Schedule posting change/i }),
		).toBeInTheDocument();

		expect(screen.getByText("Office")).toBeInTheDocument();
		expect(screen.getByText("Payroll Unit")).toBeInTheDocument();
		expect(screen.getByText("Post")).toBeInTheDocument();
		expect(screen.queryByText("Office ID")).not.toBeInTheDocument();
		expect(screen.queryByText("Payroll Unit ID")).not.toBeInTheDocument();
		expect(screen.queryByText("Post ID")).not.toBeInTheDocument();

		expect(await screen.findByRole("combobox", { name: "Office" })).toHaveTextContent(
			"Head Office",
		);
		expect(screen.getByRole("combobox", { name: "Payroll Unit" })).toHaveTextContent("HQ Payroll");
		expect(screen.getByRole("combobox", { name: "Post" })).toHaveTextContent("Clerk");
		expect(screen.getByRole("combobox", { name: "Employee Group" })).toHaveTextContent("Group A");

		openBaseUiSelect(screen.getByRole("combobox", { name: "Office" }));
		expect(await screen.findByRole("option", { name: "Regional Office" })).toBeInTheDocument();
		pickBaseUiOption("Regional Office");
		await waitFor(() => {
			expect(screen.getByRole("combobox", { name: "Office" })).toHaveTextContent("Regional Office");
		});
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
