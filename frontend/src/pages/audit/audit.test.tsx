import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";

import { toAuditDayBound } from "@/lib/api/audit";
import { queryClient } from "@/lib/query-client";
import { buildAuthMe, buildRoleAuthMe } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { buildAuditEvent, createAuditHandlers } from "@/test/msw/audit-handlers";
import { server } from "@/test/msw-server";
import { renderWithAuthProviders } from "@/test/render-app";
import type { Capability } from "@/types/auth";
import AuditPage from "./AuditPage";

const PAGE_TIMEOUT = 15_000;

function renderAuditPage() {
	return renderWithAuthProviders(
		<MemoryRouter>
			<AuditPage />
		</MemoryRouter>,
	);
}

function useAuditor(events = createAuditHandlers()) {
	const { handlers: authHandlers } = createAuthHandlers({ me: buildRoleAuthMe("auditor") });
	server.use(...authHandlers, ...events.handlers);
	return events;
}

describe("audit history", () => {
	beforeEach(() => {
		queryClient.clear();
		Object.defineProperty(window, "innerWidth", { configurable: true, value: 1024 });
	});

	it("groups the rail by date and automatically selects the newest desktop event", async () => {
		const newest = buildAuditEvent({
			id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
			entity_label: "July payroll run",
			created_at: "2026-07-18T12:00:00",
		});
		const older = buildAuditEvent({
			id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
			entity_label: "June payroll run",
			created_at: "2026-07-17T12:00:00",
		});
		useAuditor(createAuditHandlers({ events: [older, newest] }));

		renderAuditPage();
		expect(
			await screen.findByText("18 Jul, 2026", {}, { timeout: PAGE_TIMEOUT }),
		).toBeInTheDocument();
		expect(screen.getByTestId("audit-workspace")).not.toContainElement(
			screen.getByTestId("audit-filter-toolbar"),
		);
		expect(screen.getByText("17 Jul, 2026")).toBeInTheDocument();
		expect(await screen.findByTestId("audit-event-detail")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: /July payroll run/i })).toHaveAttribute(
			"aria-current",
			"true",
		);
		expect(screen.queryByText("Select an event")).not.toBeInTheDocument();
	});

	it("renders changed mutation fields only without raw JSON", async () => {
		const event = buildAuditEvent({
			id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
			entity_label: "2026-07 payroll run",
			command: "payroll_run.reverse",
			request_id: "req-reverse-001",
			before_state: { status: "posted", lock_version: 4, organization_id: "org" },
			after_state: { status: "reversed", lock_version: 5, organization_id: "org" },
			access_details: {
				reason: "Duplicate posting",
				reversal_run_id: "99999999-9999-9999-9999-999999999999",
			},
		});
		useAuditor(createAuditHandlers({ events: [event] }));
		renderAuditPage();

		const detail = await screen.findByTestId("audit-event-detail", {}, { timeout: PAGE_TIMEOUT });
		expect(within(detail).getByText("ada@example.com")).toBeInTheDocument();
		expect(within(detail).getByText("Payroll Run")).toBeInTheDocument();
		expect(within(detail).getByText(event.entity_id)).toBeInTheDocument();
		expect(within(detail).getByText("req-reverse-001")).toBeInTheDocument();
		expect(within(detail).getByText("Context")).toBeInTheDocument();
		expect(within(detail).getByText("Duplicate posting")).toBeInTheDocument();
		expect(within(detail).getByText("Status")).toBeInTheDocument();
		expect(within(detail).getByText("posted")).toBeInTheDocument();
		expect(within(detail).getByText("reversed")).toBeInTheDocument();
		expect(within(detail).queryByText("Lock version")).not.toBeInTheDocument();
		expect(within(detail).queryByText("Raw JSON")).not.toBeInTheDocument();
	});

	it("uses a dedicated access-details presentation", async () => {
		const event = buildAuditEvent({
			id: "dddddddd-dddd-dddd-dddd-dddddddddddd",
			command: "artifact.download",
			event_kind: "access",
			entity_type: "export_artifact",
			entity_label: "Payroll Register",
			before_state: null,
			after_state: null,
			resource_state: { report_type: "payroll_register", size_bytes: 4096 },
			access_details: { accessed_at: "2026-07-18T12:00:00" },
		});
		useAuditor(createAuditHandlers({ events: [event] }));
		renderAuditPage();

		const detail = await screen.findByTestId("audit-event-detail", {}, { timeout: PAGE_TIMEOUT });
		expect(within(detail).getByText("Resource")).toBeInTheDocument();
		expect(within(detail).getByText("Access Details")).toBeInTheDocument();
		expect(within(detail).getByText("Report Type")).toBeInTheDocument();
		expect(within(detail).queryByText("Before")).not.toBeInTheDocument();
	});

	it("debounces entity ID, resets filters, and replaces selection across pages", async () => {
		const audit = useAuditor(createAuditHandlers({ pageSize: 20 }));
		renderAuditPage();
		await screen.findByText("2026-07 payroll run 1", {}, { timeout: PAGE_TIMEOUT });

		const entityId = "22222222-2222-2222-2222-000000000001";
		fireEvent.change(screen.getByLabelText("Filter by Entity ID"), { target: { value: entityId } });
		await waitFor(() => {
			expect(audit.capturedListRequests.some((request) => request.entity_id === entityId)).toBe(
				true,
			);
		});
		fireEvent.click(screen.getByRole("button", { name: "Reset" }));
		await waitFor(() => expect(screen.getByLabelText("Filter by Entity ID")).toHaveValue(""));

		fireEvent.click(
			await screen.findByRole("button", { name: "Go to page 2" }, { timeout: PAGE_TIMEOUT }),
		);
		await waitFor(() => {
			expect(screen.getByRole("button", { name: /2026-07 payroll run 21/i })).toHaveAttribute(
				"aria-current",
				"true",
			);
		});
	});

	it("holds the query while entity ID is not UUID-shaped, then queries once valid", async () => {
		const audit = useAuditor(createAuditHandlers());
		renderAuditPage();
		await screen.findByText("2026-07 payroll run 1", {}, { timeout: PAGE_TIMEOUT });

		const partial = "22222222-2222";
		fireEvent.change(screen.getByLabelText("Filter by Entity ID"), {
			target: { value: partial },
		});
		expect(
			await screen.findByTestId("entity-id-invalid", {}, { timeout: PAGE_TIMEOUT }),
		).toHaveTextContent(/UUID/);
		// Past the 300ms debounce, the partial id must never reach the backend —
		// it would 422 and clear the workspace. Previous results stay (dimmed
		// placeholder) while the hint explains why nothing new is loading.
		await new Promise((resolve) => setTimeout(resolve, 500));
		expect(audit.capturedListRequests.some((request) => request.entity_id === partial)).toBe(false);
		expect(screen.getByText("2026-07 payroll run 1")).toBeInTheDocument();

		const full = "22222222-2222-2222-2222-000000000001";
		fireEvent.change(screen.getByLabelText("Filter by Entity ID"), {
			target: { value: full },
		});
		await waitFor(() =>
			expect(audit.capturedListRequests.some((request) => request.entity_id === full)).toBe(true),
		);
		expect(screen.queryByTestId("entity-id-invalid")).not.toBeInTheDocument();
	});

	it("sends IST day bounds for the picked date range", async () => {
		const audit = useAuditor(createAuditHandlers());
		renderAuditPage();
		await screen.findByText("2026-07 payroll run 1", {}, { timeout: PAGE_TIMEOUT });

		fireEvent.click(screen.getByLabelText("Filter by Date Range"));
		const now = new Date();
		let cursorIndex = now.getFullYear() * 12 + now.getMonth();
		const pickRangeDay = (iso: string) => {
			const [year, month, day] = iso.split("-").map(Number);
			const dataDay = new Date(year, month - 1, day).toLocaleDateString();
			const targetIndex = year * 12 + (month - 1);
			while (cursorIndex !== targetIndex) {
				if (cursorIndex > targetIndex) {
					fireEvent.click(screen.getByRole("button", { name: "Go to the Previous Month" }));
					cursorIndex -= 1;
				} else {
					fireEvent.click(screen.getByRole("button", { name: "Go to the Next Month" }));
					cursorIndex += 1;
				}
			}
			const dayButton = document.querySelector(`[data-day="${dataDay}"]`);
			if (!dayButton) throw new Error(`Calendar day not found for ${iso} (${dataDay})`);
			fireEvent.click(dayButton);
		};
		pickRangeDay("2026-08-01");
		pickRangeDay("2026-08-05");

		await waitFor(() => {
			const last = audit.capturedListRequests.at(-1);
			expect(last?.from).toBe("2026-08-01T00:00:00+05:30");
			expect(last?.to).toBe("2026-08-05T23:59:59.999999+05:30");
		});
	});

	it("renders one empty state without a detail pane", async () => {
		useAuditor(createAuditHandlers({ empty: true }));
		renderAuditPage();
		expect(
			await screen.findByText("No Audit Events", {}, { timeout: PAGE_TIMEOUT }),
		).toBeInTheDocument();
		expect(screen.queryByTestId("audit-detail-panel")).not.toBeInTheDocument();
		expect(screen.queryByText("Select an event")).not.toBeInTheDocument();
	});

	it("opens contextual event details in a mobile sheet", async () => {
		Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
		const event = buildAuditEvent({
			id: "ffffffff-ffff-ffff-ffff-ffffffffffff",
			entity_label: "Mobile payroll run",
			command: "approve",
		});
		useAuditor(createAuditHandlers({ events: [event] }));
		renderAuditPage();

		expect(screen.queryByTestId("audit-event-detail")).not.toBeInTheDocument();
		fireEvent.click(
			await screen.findByRole("button", { name: /Mobile payroll run/i }, { timeout: PAGE_TIMEOUT }),
		);
		const dialog = await screen.findByRole("dialog");
		expect(within(dialog).getByText("Mobile payroll run")).toBeInTheDocument();
		expect(await within(dialog).findByTestId("audit-event-detail")).toBeInTheDocument();
	});

	it("blocks access without view_audit", async () => {
		const me = buildAuthMe({
			organization: {
				id: "org-acme",
				name: "Acme Payroll",
				slug: "acme-payroll",
			},
			membership: {
				role: "payroll_preparer",
				capabilities: ["view_master_data", "create_run"] as Capability[],
			},
		});
		server.use(...createAuthHandlers({ me }).handlers);
		renderAuditPage();
		expect(
			await screen.findByText("You Don't Have Access", {}, { timeout: PAGE_TIMEOUT }),
		).toBeInTheDocument();
	});
});

describe("toAuditDayBound", () => {
	it("emits ACCORD-timezone-aware day bounds instead of naive local times", () => {
		expect(toAuditDayBound(new Date(2026, 7, 1), "start")).toBe("2026-08-01T00:00:00+05:30");
		expect(toAuditDayBound(new Date(2026, 7, 1), "end")).toBe("2026-08-01T23:59:59.999999+05:30");
	});
});
