import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { RecurringInstructionVersionCreate } from "@/lib/api/pay-setup";
import { queryClient } from "@/lib/query-client";
import { buildRoleAuthMe } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { openBaseUiSelect, pickBaseUiOption } from "@/test/helpers";
import { server } from "@/test/msw-server";
import { renderApp } from "@/test/render-app";

import { buildEmployeeDetail, createEmployeeHandlers } from "../employee-handlers";
import {
	buildAccommodation,
	buildAdvance,
	buildRecurringInstruction,
	createPayrollSetupHandlers,
} from "./payroll-setup-handlers";

// Warm lazy-loaded modules so Suspense does not stall tests.
import "@/pages/employees/EmployeeDetailPage";

const PAGE_TIMEOUT = 15_000;
const EMPLOYEE_ID = "emp-1";

function setupEmployeePage(
	role: "organization_administrator" | "payroll_reviewer" = "organization_administrator",
	payrollOptions: Parameters<typeof createPayrollSetupHandlers>[0] = {},
) {
	const { handlers: authHandlers } = createAuthHandlers({
		me: buildRoleAuthMe(role),
	});
	const detail = buildEmployeeDetail({
		id: EMPLOYEE_ID,
		employee_number: "E-001",
	});
	const { handlers: employeeHandlers } = createEmployeeHandlers({
		employees: [
			{
				id: EMPLOYEE_ID,
				employee_number: "E-001",
				name: "Alice Example",
				sevarth_id: "SEV-001",
				retirement_regime: "gpf",
			},
		],
		details: { [EMPLOYEE_ID]: detail },
	});
	const { handlers: payrollHandlers } = createPayrollSetupHandlers({
		employeeId: EMPLOYEE_ID,
		...payrollOptions,
	});
	server.use(...authHandlers, ...employeeHandlers, ...payrollHandlers);
	renderApp({ initialEntries: [`/employees/${EMPLOYEE_ID}`] });
}

async function openEmployeeTab(tabName: string | RegExp) {
	expect(await screen.findByText("••••234F", {}, { timeout: PAGE_TIMEOUT })).toBeInTheDocument();
	fireEvent.click(await screen.findByRole("tab", { name: tabName }, { timeout: PAGE_TIMEOUT }));
}

describe("Employee payroll-setup tabs", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	afterEach(() => {
		cleanup();
	});

	it(
		"renders seeded recurring items, advances, and accommodation",
		async () => {
			setupEmployeePage("organization_administrator", {
				recurringInstructions: [
					buildRecurringInstruction({
						id: "ri-1",
						employee_id: EMPLOYEE_ID,
						component_id: "pc-hra",
						amount: "2500.00",
					}),
				],
				advances: [
					buildAdvance({
						id: "adv-1",
						employee_id: EMPLOYEE_ID,
						principal: "100000.00",
						installment_amount: "5000.00",
						installments_recovered_opening: 2,
						installments_total: 20,
					}),
				],
				accommodation: [
					buildAccommodation({
						id: "acc-1",
						employee_id: EMPLOYEE_ID,
						license_fee: "1200.00",
						informational_hra_foregone: "8500.00",
						quarters_identifier: "B-12",
					}),
				],
			});

			await openEmployeeTab("Recurring Items");
			expect(
				await screen.findByTestId("recurring-items-tab", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(await screen.findByText(/HRA — House Rent Allowance/)).toBeInTheDocument();
			expect(screen.getByText("2500.00")).toBeInTheDocument();

			fireEvent.click(screen.getByRole("tab", { name: "Advances" }));
			expect(
				await screen.findByTestId("advances-tab", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(await screen.findByText("HBA")).toBeInTheDocument();
			expect(screen.getByText("100000.00")).toBeInTheDocument();
			expect(screen.getByText("5000.00")).toBeInTheDocument();
			expect(screen.getByText("2/20")).toBeInTheDocument();

			fireEvent.click(screen.getByRole("tab", { name: "Accommodation" }));
			expect(
				await screen.findByTestId("accommodation-tab", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(await screen.findByText(/Mumbai — B-12/)).toBeInTheDocument();
			expect(screen.getByTestId("accommodation-license-fee")).toHaveTextContent("1200.00");
			expect(screen.getByTestId("accommodation-foregone-hra")).toHaveTextContent("8500.00");
			expect(screen.getByTestId("accommodation-foregone-caption")).toHaveTextContent(
				/Informational only/,
			);
		},
		PAGE_TIMEOUT,
	);

	it(
		"adds a recurring instruction on the happy path",
		async () => {
			setupEmployeePage("organization_administrator", {
				recurringInstructions: [],
			});

			await openEmployeeTab("Recurring Items");
			fireEvent.click(
				await screen.findByRole("button", { name: /^Add$/ }, { timeout: PAGE_TIMEOUT }),
			);

			expect(await screen.findByRole("heading", { name: "Add instruction" })).toBeInTheDocument();
			openBaseUiSelect(screen.getByLabelText("Component"));
			pickBaseUiOption(/CCA — City Compensatory Allowance/);
			fireEvent.change(screen.getByLabelText("Effective from"), {
				target: { value: "2026-03-01" },
			});
			fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "1500.00" } });
			fireEvent.click(screen.getByRole("button", { name: /^Add$/ }));

			await waitFor(() => {
				expect(screen.queryByRole("heading", { name: "Add instruction" })).not.toBeInTheDocument();
			});
			expect(await screen.findByText(/CCA — City Compensatory Allowance/)).toBeInTheDocument();
			expect(screen.getByText("1500.00")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"surfaces 409 overlap inline in the add-instruction dialog",
		async () => {
			setupEmployeePage("organization_administrator", {
				recurringInstructions: [],
				createInstructionError: {
					status: 409,
					body: { detail: "Recurring instruction periods overlap." },
				},
			});

			await openEmployeeTab("Recurring Items");
			fireEvent.click(
				await screen.findByRole("button", { name: /^Add$/ }, { timeout: PAGE_TIMEOUT }),
			);
			expect(await screen.findByRole("heading", { name: "Add instruction" })).toBeInTheDocument();
			openBaseUiSelect(screen.getByLabelText("Component"));
			pickBaseUiOption(/HRA — House Rent Allowance/);
			fireEvent.change(screen.getByLabelText("Effective from"), {
				target: { value: "2026-04-01" },
			});
			fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "2000.00" } });
			fireEvent.click(screen.getByRole("button", { name: /^Add$/ }));

			expect(
				await screen.findByTestId("ri-overlap-error", {}, { timeout: PAGE_TIMEOUT }),
			).toHaveTextContent("Recurring instruction periods overlap.");
			expect(screen.getByRole("heading", { name: "Add instruction" })).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"ends an instruction by sending end_on",
		async () => {
			const captured: { body?: RecurringInstructionVersionCreate } = {};
			setupEmployeePage("organization_administrator", {
				onCreateInstructionVersion: (_id, body) => {
					captured.body = body;
				},
			});

			await openEmployeeTab("Recurring Items");
			fireEvent.click(
				await screen.findByRole("button", { name: "End" }, { timeout: PAGE_TIMEOUT }),
			);
			expect(await screen.findByRole("heading", { name: "End instruction" })).toBeInTheDocument();
			fireEvent.change(screen.getByLabelText("End on"), { target: { value: "2026-06-30" } });
			fireEvent.change(screen.getByLabelText("Change reason (optional)"), {
				target: { value: "Left quarters" },
			});
			fireEvent.click(screen.getByRole("button", { name: "End instruction" }));

			await waitFor(() => {
				expect(captured.body).toBeDefined();
			});
			expect(captured.body).toMatchObject({
				end_on: "2026-06-30",
				change_reason: "Left quarters",
			});
			expect(captured.body).not.toHaveProperty("effective_from");
			expect(captured.body?.amount).toBeUndefined();
			expect(captured.body?.rate).toBeUndefined();
		},
		PAGE_TIMEOUT,
	);

	it(
		"creates an advance and surfaces installment client validation",
		async () => {
			setupEmployeePage("organization_administrator", {
				advances: [],
			});

			await openEmployeeTab("Advances");
			fireEvent.click(
				await screen.findByRole("button", { name: /^Add$/ }, { timeout: PAGE_TIMEOUT }),
			);
			expect(await screen.findByRole("heading", { name: "Add advance" })).toBeInTheDocument();

			const form = screen.getByTestId("add-advance-form");
			fireEvent.change(within(form).getByLabelText("Principal"), {
				target: { value: "50000.00" },
			});
			fireEvent.change(within(form).getByLabelText("Sanctioned on"), {
				target: { value: "2026-05-01" },
			});
			fireEvent.change(within(form).getByLabelText("Effective from"), {
				target: { value: "2026-05-01" },
			});
			fireEvent.change(within(form).getByLabelText("Installment amount"), {
				target: { value: "60000.00" },
			});
			fireEvent.change(within(form).getByLabelText("Installments total"), {
				target: { value: "10" },
			});
			fireEvent.click(within(form).getByRole("button", { name: /^Add$/ }));

			expect(await screen.findByTestId("advance-form-error")).toHaveTextContent(
				/Installment amount must be less than or equal to principal/,
			);

			fireEvent.change(within(form).getByLabelText("Installment amount"), {
				target: { value: "5000.00" },
			});
			fireEvent.click(within(form).getByRole("button", { name: /^Add$/ }));

			await waitFor(() => {
				expect(screen.queryByRole("heading", { name: "Add advance" })).not.toBeInTheDocument();
			});
			expect(await screen.findByText("50000.00")).toBeInTheDocument();
			expect(screen.getByText("5000.00")).toBeInTheDocument();
			expect(screen.getByText("0/10")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"shows license fee and foregone HRA distinctly with caption",
		async () => {
			setupEmployeePage("organization_administrator", {
				accommodation: [
					buildAccommodation({
						id: "acc-1",
						employee_id: EMPLOYEE_ID,
						license_fee: "1200.00",
						informational_hra_foregone: "8500.00",
					}),
				],
			});

			await openEmployeeTab("Accommodation");

			const card = await screen.findByTestId(
				"accommodation-card-acc-1",
				{},
				{ timeout: PAGE_TIMEOUT },
			);
			expect(within(card).getByTestId("accommodation-license-fee")).toHaveTextContent("1200.00");
			expect(within(card).getByTestId("accommodation-foregone-hra")).toHaveTextContent("8500.00");
			expect(within(card).getByTestId("accommodation-foregone-caption")).toHaveTextContent(
				/not a payroll charge/i,
			);
			expect(within(card).getByText("License fee")).toBeInTheDocument();
			expect(within(card).getByText("Foregone HRA")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"hides write actions without manage_master_data",
		async () => {
			setupEmployeePage("payroll_reviewer");

			await openEmployeeTab("Recurring Items");
			expect(
				await screen.findByTestId("recurring-items-tab", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /^Add$/ })).not.toBeInTheDocument();
			expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
			expect(screen.queryByRole("button", { name: "End" })).not.toBeInTheDocument();

			fireEvent.click(screen.getByRole("tab", { name: "Advances" }));
			expect(await screen.findByTestId("advances-tab")).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /^Add$/ })).not.toBeInTheDocument();
			expect(
				screen.queryByRole("button", { name: "Add" }),
			).not.toBeInTheDocument();

			fireEvent.click(screen.getByRole("tab", { name: "Accommodation" }));
			expect(await screen.findByTestId("accommodation-tab")).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /^Add$/ })).not.toBeInTheDocument();
			expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});
