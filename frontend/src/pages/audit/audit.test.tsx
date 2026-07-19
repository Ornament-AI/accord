import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";

import { queryClient } from "@/lib/query-client";
import { buildAuthMe, buildRoleAuthMe } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { server } from "@/test/msw-server";
import { renderWithAuthProviders } from "@/test/render-app";
import type { Capability } from "@/types/auth";

import AuditPage from "./AuditPage";
import { buildAuditEvent, createAuditHandlers } from "./audit-handlers";

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

describe("Atlas-parity audit history", () => {
	beforeEach(() => {
		queryClient.clear();
		Object.defineProperty(window, "innerWidth", { configurable: true, value: 1024 });
	});

	it("groups the rail by date and automatically selects the newest desktop event", async () => {
		const newest = buildAuditEvent({
			id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
			entity_label: "July Regular run",
			created_at: "2026-07-18T12:00:00",
		});
		const older = buildAuditEvent({
			id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
			entity_label: "June Regular run",
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
		expect(screen.getByRole("button", { name: /July Regular run/i })).toHaveAttribute(
			"aria-current",
			"true",
		);
		expect(screen.queryByText("Select an event")).not.toBeInTheDocument();
	});

	it("renders changed mutation fields only without raw JSON", async () => {
		const event = buildAuditEvent({
			id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
			entity_label: "2026-07 Regular run",
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
		expect(within(detail).getByText(/Ada Lovelace \(ada@example.com\)/)).toBeInTheDocument();
		expect(within(detail).getByText("Payroll run")).toBeInTheDocument();
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
		expect(within(detail).getByText("Report type")).toBeInTheDocument();
		expect(within(detail).queryByText("Before")).not.toBeInTheDocument();
	});

	it("shows the minimal legacy message", async () => {
		const event = buildAuditEvent({
			id: "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
			event_kind: null,
			has_structured_detail: false,
			before_state: null,
			after_state: null,
		});
		useAuditor(createAuditHandlers({ events: [event] }));
		renderAuditPage();
		expect(
			await screen.findByText(
				"Detailed changes were not recorded for this legacy event.",
				{},
				{ timeout: PAGE_TIMEOUT },
			),
		).toBeInTheDocument();
	});

	it("debounces entity ID, resets filters, and replaces selection across pages", async () => {
		const audit = useAuditor(createAuditHandlers({ pageSize: 20 }));
		renderAuditPage();
		await screen.findByText("2026-07 Regular run 1", {}, { timeout: PAGE_TIMEOUT });

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
			expect(screen.getByRole("button", { name: /2026-07 Regular run 21/i })).toHaveAttribute(
				"aria-current",
				"true",
			);
		});
	});

	it("renders one empty state without a detail pane", async () => {
		useAuditor(createAuditHandlers({ empty: true }));
		renderAuditPage();
		expect(
			await screen.findByText("No audit events", {}, { timeout: PAGE_TIMEOUT }),
		).toBeInTheDocument();
		expect(screen.queryByTestId("audit-detail-panel")).not.toBeInTheDocument();
		expect(screen.queryByText("Select an event")).not.toBeInTheDocument();
	});

	it("opens contextual event details in a mobile sheet", async () => {
		Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
		const event = buildAuditEvent({
			id: "ffffffff-ffff-ffff-ffff-ffffffffffff",
			entity_label: "Mobile Regular run",
			command: "approve",
		});
		useAuditor(createAuditHandlers({ events: [event] }));
		renderAuditPage();

		expect(screen.queryByTestId("audit-event-detail")).not.toBeInTheDocument();
		fireEvent.click(
			await screen.findByRole("button", { name: /Mobile Regular run/i }, { timeout: PAGE_TIMEOUT }),
		);
		const dialog = await screen.findByRole("dialog");
		expect(within(dialog).getByText("Mobile Regular run")).toBeInTheDocument();
		expect(await within(dialog).findByTestId("audit-event-detail")).toBeInTheDocument();
	});

	it("blocks access without view_audit", async () => {
		const me = buildAuthMe({
			active_organization: {
				id: "org-acme",
				name: "Acme Payroll",
				slug: "acme-payroll",
				role: "payroll_preparer",
				capabilities: ["view_master_data", "create_run"] as Capability[],
			},
		});
		server.use(...createAuthHandlers({ me }).handlers);
		renderAuditPage();
		expect(
			await screen.findByText("You don't have access", {}, { timeout: PAGE_TIMEOUT }),
		).toBeInTheDocument();
	});
});
