import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RecurringInstructionVersionCreate } from "@/lib/api/employee-payroll-setup";
import { queryClient } from "@/lib/query-client";
import { buildRoleAuthMe } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { openBaseUiSelect, pickBaseUiOption, pickDateByLabel } from "@/test/helpers";
import { buildEmployeeDetail, createEmployeeHandlers } from "@/test/msw/employee-handlers";
import {
	buildAccommodation,
	buildAdvance,
	buildRecurringInstruction,
	createPayrollSetupHandlers,
} from "@/test/msw/payroll-setup-handlers";
import { server } from "@/test/msw-server";
import { renderApp } from "@/test/render-app";

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
			expect(await screen.findByText("House Rent Allowance (HRA)")).toBeInTheDocument();
			expect(screen.getByText("2500.00")).toBeInTheDocument();
			expect(
				screen.queryByRole("columnheader", { name: /Effective Range/i }),
			).not.toBeInTheDocument();

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
				"Foregone HRA",
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

			expect(await screen.findByRole("heading", { name: "Add Instruction" })).toBeInTheDocument();
			const instructionDialog = screen.getByRole("dialog");
			openBaseUiSelect(within(instructionDialog).getByLabelText("Component"));
			pickBaseUiOption(/City Compensatory Allowance/);
			pickDateByLabel("Effective From", "2026-03-01");
			fireEvent.change(within(instructionDialog).getByLabelText("Amount"), {
				target: { value: "1500.00" },
			});
			fireEvent.click(within(instructionDialog).getByRole("button", { name: /^Add$/ }));

			await waitFor(() => {
				expect(screen.queryByRole("heading", { name: "Add Instruction" })).not.toBeInTheDocument();
			});
			expect(await screen.findByText("City Compensatory Allowance (CCA)")).toBeInTheDocument();
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
			expect(await screen.findByRole("heading", { name: "Add Instruction" })).toBeInTheDocument();
			const instructionDialog = screen.getByRole("dialog");
			openBaseUiSelect(within(instructionDialog).getByLabelText("Component"));
			pickBaseUiOption(/House Rent Allowance/);
			pickDateByLabel("Effective From", "2026-04-01");
			fireEvent.change(within(instructionDialog).getByLabelText("Amount"), {
				target: { value: "2000.00" },
			});
			fireEvent.click(within(instructionDialog).getByRole("button", { name: /^Add$/ }));

			expect(
				await screen.findByTestId("ri-overlap-error", {}, { timeout: PAGE_TIMEOUT }),
			).toHaveTextContent("Recurring instruction periods overlap.");
			expect(screen.getByRole("heading", { name: "Add Instruction" })).toBeInTheDocument();
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
				await screen.findByRole("button", { name: "New Version" }, { timeout: PAGE_TIMEOUT }),
			);
			expect(await screen.findByRole("heading", { name: "New Version" })).toBeInTheDocument();
			fireEvent.click(screen.getByRole("button", { name: "End" }));
			expect(await screen.findByRole("heading", { name: "End Instruction" })).toBeInTheDocument();
			pickDateByLabel("End On", "2026-06-30");
			fireEvent.click(screen.getByRole("button", { name: "End Instruction" }));

			await waitFor(() => {
				expect(captured.body).toBeDefined();
			});
			expect(captured.body).toMatchObject({
				end_on: "2026-06-30",
				change_reason: null,
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
			expect(await screen.findByRole("heading", { name: "Add Advance" })).toBeInTheDocument();

			const form = screen.getByTestId("add-advance-form");
			fireEvent.change(within(form).getByLabelText("Principal"), {
				target: { value: "50000.00" },
			});
			pickDateByLabel("Sanctioned On", "2026-05-01");
			pickDateByLabel("Effective From", "2026-05-01");
			fireEvent.change(within(form).getByLabelText("Installment Amount"), {
				target: { value: "60000.00" },
			});
			fireEvent.change(within(form).getByLabelText("Installments Total"), {
				target: { value: "10" },
			});
			fireEvent.click(within(form).getByRole("button", { name: /^Add$/ }));

			expect(await screen.findByTestId("advance-form-error")).toHaveTextContent(
				/Installment amount must be less than or equal to principal/,
			);

			fireEvent.change(within(form).getByLabelText("Installment Amount"), {
				target: { value: "5000.00" },
			});
			fireEvent.click(within(form).getByRole("button", { name: /^Add$/ }));

			await waitFor(() => {
				expect(screen.queryByRole("heading", { name: "Add Advance" })).not.toBeInTheDocument();
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

			const row = await screen.findByTestId(
				"accommodation-row-acc-1",
				{},
				{ timeout: PAGE_TIMEOUT },
			);
			expect(within(row).getByTestId("accommodation-license-fee")).toHaveTextContent("1200.00");
			expect(within(row).getByTestId("accommodation-foregone-hra")).toHaveTextContent("8500.00");
			expect(screen.getByTestId("accommodation-foregone-caption")).toHaveTextContent(
				"Foregone HRA",
			);
			expect(screen.getByRole("columnheader", { name: /License Fee/i })).toBeInTheDocument();
			expect(screen.getByRole("columnheader", { name: /Foregone HRA/i })).toBeInTheDocument();
			expect(screen.queryByRole("columnheader", { name: "Actions" })).not.toBeInTheDocument();
			fireEvent.click(within(row).getByRole("button", { name: "Update Fee" }));
			expect(
				await screen.findByRole("heading", { name: "New Charge Version" }),
			).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"captures quarters address and exact charge breakdowns for create and version flows",
		async () => {
			const onCreateAccommodation = vi.fn();
			const onUpdateAccommodation = vi.fn();
			const onCreateAccommodationChargeVersion = vi.fn();
			setupEmployeePage("organization_administrator", {
				accommodation: [],
				onCreateAccommodation,
				onUpdateAccommodation,
				onCreateAccommodationChargeVersion,
			});

			await openEmployeeTab("Accommodation");
			fireEvent.click(
				await screen.findByRole("button", { name: /^Add$/ }, { timeout: PAGE_TIMEOUT }),
			);
			const addDialog = await screen.findByRole("dialog");
			fireEvent.change(within(addDialog).getByLabelText("Quarters Identifier"), {
				target: { value: "C-18" },
			});
			fireEvent.change(within(addDialog).getByLabelText("Quarters Address"), {
				target: { value: "18 Marine Drive, Mumbai" },
			});
			pickDateByLabel("Effective From", "2026-06-01");
			fireEvent.change(within(addDialog).getByLabelText("License Fee"), {
				target: { value: "1200" },
			});
			fireEvent.change(within(addDialog).getByLabelText("House Rent"), {
				target: { value: "900" },
			});
			fireEvent.change(within(addDialog).getByLabelText("Service Charge"), {
				target: { value: "200" },
			});
			fireEvent.change(within(addDialog).getByLabelText("Parking Charge"), {
				target: { value: "100" },
			});
			fireEvent.click(within(addDialog).getByRole("button", { name: /^Add$/ }));

			await waitFor(() =>
				expect(onCreateAccommodation).toHaveBeenCalledWith({
					quarters_location: "mumbai",
					quarters_identifier: "C-18",
					quarters_address: "18 Marine Drive, Mumbai",
					charge: {
						effective_from: "2026-06-01",
						license_fee: "1200",
						informational_hra_foregone: null,
						house_rent: "900",
						service_charge: "200",
						parking_charge: "100",
						additional_parking_charge: null,
					},
				}),
			);
			expect(await screen.findByText("18 Marine Drive, Mumbai")).toBeInTheDocument();

			const row = screen.getByTestId("accommodation-row-acc-1");
			expect(within(row).getByTestId("accommodation-charge-breakdown")).toHaveTextContent(
				"House Rent: 900 · Service Charge: 200 · Parking Charge: 100",
			);
			fireEvent.click(within(row).getByRole("button", { name: "Edit Assignment" }));
			const assignmentDialog = await screen.findByRole("dialog");
			fireEvent.change(within(assignmentDialog).getByLabelText("Quarters Identifier"), {
				target: { value: "C-18A" },
			});
			fireEvent.change(within(assignmentDialog).getByLabelText("Quarters Address"), {
				target: { value: "18 Marine Drive, Churchgate, Mumbai" },
			});
			fireEvent.click(within(assignmentDialog).getByRole("button", { name: "Save" }));

			await waitFor(() =>
				expect(onUpdateAccommodation).toHaveBeenCalledWith("acc-1", {
					quarters_identifier: "C-18A",
					quarters_address: "18 Marine Drive, Churchgate, Mumbai",
				}),
			);
			expect(await screen.findByText("18 Marine Drive, Churchgate, Mumbai")).toBeInTheDocument();

			fireEvent.click(within(row).getByRole("button", { name: "Update Fee" }));
			const versionDialog = await screen.findByRole("dialog");
			pickDateByLabel("Effective From", "2026-07-01");
			fireEvent.change(within(versionDialog).getByLabelText("License Fee"), {
				target: { value: "1500" },
			});
			fireEvent.change(within(versionDialog).getByLabelText("House Rent"), {
				target: { value: "1000" },
			});
			fireEvent.change(within(versionDialog).getByLabelText("Service Charge"), {
				target: { value: "250" },
			});
			fireEvent.change(within(versionDialog).getByLabelText("Parking Charge"), {
				target: { value: "150" },
			});
			fireEvent.change(within(versionDialog).getByLabelText("Additional Parking Charge"), {
				target: { value: "100" },
			});
			fireEvent.click(within(versionDialog).getByRole("button", { name: "Create Version" }));

			await waitFor(() =>
				expect(onCreateAccommodationChargeVersion).toHaveBeenCalledWith("acc-1", {
					effective_from: "2026-07-01",
					license_fee: "1500",
					informational_hra_foregone: null,
					house_rent: "1000",
					service_charge: "250",
					parking_charge: "150",
					additional_parking_charge: "100",
					change_reason: null,
				}),
			);
		},
		PAGE_TIMEOUT,
	);

	it(
		"accepts exact decimal charge breakdowns without floating-point drift",
		async () => {
			const onCreateAccommodation = vi.fn();
			setupEmployeePage("organization_administrator", {
				accommodation: [],
				onCreateAccommodation,
			});

			await openEmployeeTab("Accommodation");
			fireEvent.click(
				await screen.findByRole("button", { name: /^Add$/ }, { timeout: PAGE_TIMEOUT }),
			);
			const dialog = await screen.findByRole("dialog");
			fireEvent.change(within(dialog).getByLabelText("Quarters Identifier"), {
				target: { value: "D-1" },
			});
			pickDateByLabel("Effective From", "2026-06-01");
			fireEvent.change(within(dialog).getByLabelText("License Fee"), {
				target: { value: "0.30" },
			});
			fireEvent.change(within(dialog).getByLabelText("House Rent"), {
				target: { value: "0.10" },
			});
			fireEvent.change(within(dialog).getByLabelText("Service Charge"), {
				target: { value: "0.20" },
			});
			fireEvent.click(within(dialog).getByRole("button", { name: /^Add$/ }));

			await waitFor(() => expect(onCreateAccommodation).toHaveBeenCalledOnce());
			expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
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
			expect(screen.queryByRole("button", { name: "New Version" })).not.toBeInTheDocument();
			expect(screen.queryByRole("button", { name: "End" })).not.toBeInTheDocument();

			fireEvent.click(screen.getByRole("tab", { name: "Advances" }));
			expect(await screen.findByTestId("advances-tab")).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /^Add$/ })).not.toBeInTheDocument();
			expect(screen.queryByRole("button", { name: "Update Installment" })).not.toBeInTheDocument();

			fireEvent.click(screen.getByRole("tab", { name: "Accommodation" }));
			expect(await screen.findByTestId("accommodation-tab")).toBeInTheDocument();
			expect(screen.queryByRole("button", { name: /^Add$/ })).not.toBeInTheDocument();
			expect(screen.queryByRole("button", { name: "Update Fee" })).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});
