import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/contexts/AuthContext";
import { todayApiDate } from "@/lib/calendar-date";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { buildAuthMe, buildRoleAuthMe, ROLE_CAPABILITIES } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { openBaseUiSelect, pickBaseUiOption, pickDateByLabel } from "@/test/helpers";
import { buildEmployeeDetail, createEmployeeHandlers } from "@/test/msw/employee-handlers";
import { buildOffice, buildPost, createOrgSetupHandlers } from "@/test/msw/org-setup-handlers";
import { server } from "@/test/msw-server";
import { renderApp } from "@/test/render-app";
import type { Capability } from "@/types/auth";
import { CreateEmployeeDialog } from "./CreateEmployeeDialog";
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
				organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
				},
				membership: {
					role: "organization_administrator",
					capabilities: ROLE_CAPABILITIES.organization_administrator,
				},
			});
			const withoutReveal = buildAuthMe({
				organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
				},
				membership: {
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

	it("keeps GPF jurisdiction optional and surfaces 409 on duplicate number", async () => {
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

		fireEvent.click(screen.getByRole("button", { name: "Create" }));
		expect(await screen.findByText("This employee number is already in use")).toBeInTheDocument();
	});

	it("submits nullable profile fields plus pay and bank groups without optional values", async () => {
		const onCreate = vi.fn();
		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: employeeHandlers } = createEmployeeHandlers({ onCreate });
		const { handlers: orgHandlers } = createOrgSetupHandlers();
		server.use(...authHandlers, ...employeeHandlers, ...orgHandlers);

		renderCreateDialog();
		await screen.findByRole("heading", { name: "New Employee" });
		fireEvent.change(screen.getByLabelText("Employee Number"), { target: { value: "E-NEW" } });
		fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New Employee" } });
		fireEvent.change(screen.getByLabelText("Pension Account"), {
			target: { value: "PENSION-123" },
		});
		fireEvent.change(screen.getByLabelText("Payroll Export Remark"), {
			target: { value: "Transferred from deputation" },
		});

		fireEvent.click(screen.getByRole("tab", { name: "Pay" }));
		fireEvent.change(screen.getByLabelText("Basic Pay"), { target: { value: "51000" } });

		fireEvent.click(screen.getByRole("tab", { name: "Bank" }));
		fireEvent.change(screen.getByLabelText("Account Number"), { target: { value: "123456" } });
		fireEvent.change(screen.getByLabelText("IFSC"), { target: { value: "SBIN0001234" } });
		fireEvent.change(screen.getByLabelText("Bank Name"), { target: { value: "SBI" } });
		fireEvent.click(screen.getByRole("button", { name: "Create" }));

		await waitFor(() => expect(onCreate).toHaveBeenCalledOnce());
		expect(onCreate).toHaveBeenCalledWith({
			employee_number: "E-NEW",
			effective_from: todayApiDate(),
			profile: {
				name: "New Employee",
				sevarth_id: null,
				retirement_regime: "nps",
				date_of_birth: null,
				date_of_joining: null,
				payroll_export_remark: "Transferred from deputation",
				gpf_jurisdiction: null,
				pan: null,
				pran: null,
				pension_account: "PENSION-123",
				gpf_account_number: null,
				epf_number: null,
			},
			pay: { pay_matrix_level: null, basic_pay: "51000" },
			bank: {
				account_number: "123456",
				ifsc: "SBIN0001234",
				bank_name: "SBI",
				branch: null,
				is_primary_salary: true,
			},
		});
	});

	it("shows a tab-specific error instead of dropping a partial pay group", async () => {
		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: employeeHandlers } = createEmployeeHandlers();
		server.use(...authHandlers, ...employeeHandlers);

		renderCreateDialog();
		await screen.findByRole("heading", { name: "New Employee" });
		fireEvent.change(screen.getByLabelText("Employee Number"), { target: { value: "E-NEW" } });
		fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New Employee" } });
		fireEvent.click(screen.getByRole("tab", { name: "Pay" }));
		fireEvent.change(screen.getByLabelText("Pay Matrix Level"), { target: { value: "S-20" } });
		fireEvent.click(screen.getByRole("button", { name: "Create" }));

		expect(await screen.findByRole("alert")).toHaveTextContent(
			"Basic pay is required when adding pay details.",
		);
		expect(screen.getByRole("tab", { name: "Pay" })).toHaveAttribute("aria-selected", "true");
	});

	it("shows named office / post selectors in posting section", async () => {
		const officeId = "db4cb0bd-bd7f-45f7-986a-1acc0846f2f8";
		const postId = "f9e8d7c6-b5a4-3210-9876-543210fedcba";

		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const { handlers: employeeHandlers } = createEmployeeHandlers();
		const { handlers: orgHandlers } = createOrgSetupHandlers({
			offices: [
				buildOffice({ id: officeId, name: "Head Office" }),
				buildOffice({ id: "office-2", name: "Regional Office" }),
			],
			posts: [
				buildPost({ id: postId, designation: "Clerk", class_name: "Class III" }),
				buildPost({
					id: "post-2",
					designation: "Officer",
					class_name: "Class I",
					pay_bill_heading: "General Establishment",
				}),
			],
		});
		server.use(...authHandlers, ...employeeHandlers, ...orgHandlers);

		renderCreateDialog();
		await screen.findByRole("heading", { name: "New Employee" });

		fireEvent.click(screen.getByRole("tab", { name: "Posting" }));

		expect(screen.getByText("Office")).toBeInTheDocument();
		expect(screen.getByText("Post")).toBeInTheDocument();
		expect(screen.queryByText("Payroll Unit")).not.toBeInTheDocument();
		expect(screen.queryByText("Employee Group")).not.toBeInTheDocument();
		expect(screen.queryByText("Office ID")).not.toBeInTheDocument();
		expect(screen.queryByText("Post ID")).not.toBeInTheDocument();

		expect(await screen.findByRole("combobox", { name: "Office" })).toHaveTextContent(
			"Select office",
		);
		expect(screen.getByRole("combobox", { name: "Post" })).toHaveTextContent("Select post");
		expect(screen.getByRole("combobox", { name: "Pay Bill Group" })).toHaveTextContent(
			"Same as designation post",
		);

		openBaseUiSelect(screen.getByRole("combobox", { name: "Office" }));
		expect(await screen.findByRole("option", { name: "Head Office" })).toBeInTheDocument();
		expect(screen.getByRole("option", { name: "Regional Office" })).toBeInTheDocument();
		pickBaseUiOption("Head Office");
		await waitFor(() => {
			expect(screen.getByRole("combobox", { name: "Office" })).toHaveTextContent("Head Office");
		});

		openBaseUiSelect(screen.getByRole("combobox", { name: "Post" }));
		pickBaseUiOption("Clerk");
		await waitFor(() => {
			expect(screen.getByRole("combobox", { name: "Post" })).toHaveTextContent("Clerk");
		});

		openBaseUiSelect(screen.getByRole("combobox", { name: "Pay Bill Group" }));
		pickBaseUiOption("General Establishment");
		await waitFor(() => {
			expect(screen.getByRole("combobox", { name: "Pay Bill Group" })).toHaveTextContent(
				"General Establishment",
			);
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
			await screen.findByRole("heading", { name: /Schedule Profile Change/i }),
		).toBeInTheDocument();
		fireEvent.click(screen.getByRole("button", { name: "Submit" }));

		expect(await screen.findByRole("alert")).toHaveTextContent("Version periods overlap.");
	});

	it("shows named office / post selectors for posting changes", async () => {
		const officeId = "db4cb0bd-bd7f-45f7-986a-1acc0846f2f8";
		const postId = "f9e8d7c6-b5a4-3210-9876-543210fedcba";

		const { handlers: authHandlers } = createAuthHandlers({
			me: buildRoleAuthMe("organization_administrator"),
		});
		const onCreateVersion = vi.fn();
		const { handlers: employeeHandlers } = createEmployeeHandlers({ onCreateVersion });
		const { handlers: orgHandlers } = createOrgSetupHandlers({
			offices: [
				buildOffice({ id: officeId, name: "Head Office" }),
				buildOffice({ id: "office-2", name: "Regional Office" }),
			],
			posts: [
				buildPost({ id: postId, designation: "Clerk", class_name: "Class III" }),
				buildPost({
					id: "post-2",
					designation: "Officer",
					class_name: "Class I",
					pay_bill_heading: "General Establishment",
				}),
			],
		});
		server.use(...authHandlers, ...employeeHandlers, ...orgHandlers);

		const posting = {
			id: "posting-1",
			effective_from: "2026-01-01",
			effective_to: null,
			office_id: officeId,
			post_id: postId,
			pay_bill_post_id: null,
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
			await screen.findByRole("heading", { name: /Schedule Posting Change/i }),
		).toBeInTheDocument();

		expect(screen.getByText("Office")).toBeInTheDocument();
		expect(screen.getByText("Post")).toBeInTheDocument();
		expect(screen.queryByText("Payroll Unit")).not.toBeInTheDocument();
		expect(screen.queryByText("Employee Group")).not.toBeInTheDocument();
		expect(screen.queryByText("Office ID")).not.toBeInTheDocument();
		expect(screen.queryByText("Post ID")).not.toBeInTheDocument();

		expect(await screen.findByRole("combobox", { name: "Office" })).toHaveTextContent(
			"Head Office",
		);
		expect(screen.getByRole("combobox", { name: "Post" })).toHaveTextContent("Clerk");
		expect(screen.getByRole("combobox", { name: "Pay Bill Group" })).toHaveTextContent(
			"Same as designation post",
		);

		openBaseUiSelect(screen.getByRole("combobox", { name: "Office" }));
		expect(await screen.findByRole("option", { name: "Regional Office" })).toBeInTheDocument();
		pickBaseUiOption("Regional Office");
		await waitFor(() => {
			expect(screen.getByRole("combobox", { name: "Office" })).toHaveTextContent("Regional Office");
		});

		openBaseUiSelect(screen.getByRole("combobox", { name: "Pay Bill Group" }));
		pickBaseUiOption("General Establishment");
		fireEvent.click(screen.getByRole("button", { name: "Submit" }));
		await waitFor(() =>
			expect(onCreateVersion).toHaveBeenCalledWith(
				"emp-1",
				"posting",
				expect.objectContaining({
					office_id: "office-2",
					post_id: postId,
					pay_bill_post_id: "post-2",
				}),
			),
		);
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
				organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
				},
				membership: {
					role: "report_releaser",
					capabilities: ROLE_CAPABILITIES.report_releaser,
				},
			});
			const { handlers } = createAuthHandlers({ me });
			server.use(...handlers);

			renderApp({ initialEntries: ["/employees"] });

			expect(
				await screen.findByText("You Don't Have Access", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});
