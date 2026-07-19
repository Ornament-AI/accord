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

describe("Audit history page", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"renders audit events newest-first and supports pagination",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("auditor"),
			});
			const { handlers: auditHandlers } = createAuditHandlers({ pageSize: 20 });
			server.use(...authHandlers, ...auditHandlers);

			renderAuditPage();

			expect(
				await screen.findByTestId("audit-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();

			const rows = await screen.findAllByRole(
				"button",
				{ name: /View audit event/i },
				{ timeout: PAGE_TIMEOUT },
			);
			expect(rows.length).toBe(20);
			expect(screen.getByTestId("audit-detail-panel")).toBeInTheDocument();
			expect(screen.getByText("Select an event")).toBeInTheDocument();
			// Seed index 0 is newest and uses payroll_run.post.
			expect(rows[0]).toHaveAccessibleName(/View audit event payroll_run\.post/);

			const newestLabel = rows[0].textContent ?? "";
			fireEvent.click(screen.getByRole("button", { name: "Go to page 2" }));

			await waitFor(() => {
				const page2Rows = screen.getAllByRole("button", { name: /View audit event/i });
				expect(page2Rows.length).toBe(5);
				expect(screen.queryByRole("button", { name: newestLabel })).not.toBeInTheDocument();
			});
		},
		PAGE_TIMEOUT,
	);

	it(
		"sends text filter params and renders the date calendar without presets",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("auditor"),
			});
			const { handlers: auditHandlers, capturedListRequests } = createAuditHandlers();
			server.use(...authHandlers, ...auditHandlers);

			renderAuditPage();

			await screen.findByLabelText("Filter by Command", {}, { timeout: PAGE_TIMEOUT });

			fireEvent.change(screen.getByLabelText("Filter by Command"), {
				target: { value: "submit" },
			});
			await waitFor(() => {
				expect(capturedListRequests.some((params) => params.command === "submit")).toBe(true);
			});

			fireEvent.change(screen.getByLabelText("Filter by Entity Type"), {
				target: { value: "payroll_run" },
			});
			await waitFor(() => {
				expect(
					capturedListRequests.some(
						(params) => params.command === "submit" && params.entity_type === "payroll_run",
					),
				).toBe(true);
			});

			const entityId = "22222222-2222-2222-2222-000000000001";
			fireEvent.change(screen.getByLabelText("Search by Entity ID"), {
				target: { value: entityId },
			});
			await waitFor(() => {
				expect(capturedListRequests.some((params) => params.entity_id === entityId)).toBe(true);
			});

			fireEvent.click(screen.getByLabelText("Filter by Date Range"));
			expect(screen.getAllByRole("grid").length).toBeGreaterThan(0);
			expect(screen.queryByRole("button", { name: "Last 7 Days" })).not.toBeInTheDocument();
			expect(screen.queryByRole("button", { name: "Last 30 Days" })).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"selecting an event renders detail including summary rows",
		async () => {
			const event = buildAuditEvent({
				id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
				command: "payroll_run.post",
				entity_type: "payroll_run",
				entity_id: "33333333-3333-3333-3333-333333333333",
				actor: {
					id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
					name: "Ada Lovelace",
					email: "ada@example.com",
				},
				request_id: "req-detail-1",
				summary: {
					from_status: "approved",
					to_status: "posted",
					nested: { ignored: true },
				},
				created_at: "2026-07-18T15:30:00",
			});
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("auditor"),
			});
			const { handlers: auditHandlers } = createAuditHandlers({ events: [event] });
			server.use(...authHandlers, ...auditHandlers);

			renderAuditPage();

			fireEvent.click(
				await screen.findByRole(
					"button",
					{ name: /View audit event payroll_run\.post/i },
					{ timeout: PAGE_TIMEOUT },
				),
			);

			const detail = await screen.findByTestId("audit-event-detail", {}, { timeout: PAGE_TIMEOUT });
			expect(within(detail).getByText(/Ada Lovelace/)).toBeInTheDocument();
			expect(within(detail).getByText(/ada@example.com/)).toBeInTheDocument();
			expect(within(detail).getByText("req-detail-1")).toBeInTheDocument();
			expect(within(detail).getByText(/payroll_run · 33333333/)).toBeInTheDocument();

			const summary = within(detail).getByTestId("audit-event-summary");
			expect(within(summary).getByText("from_status")).toBeInTheDocument();
			expect(within(summary).getByText("approved")).toBeInTheDocument();
			expect(within(summary).getByText("to_status")).toBeInTheDocument();
			expect(within(summary).getByText("posted")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"shows System when actor is null",
		async () => {
			const event = buildAuditEvent({
				id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
				command: "artifact.download",
				actor: null,
				summary: { artifact_id: "art-1" },
			});
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("auditor"),
			});
			const { handlers: auditHandlers } = createAuditHandlers({ events: [event] });
			server.use(...authHandlers, ...auditHandlers);

			renderAuditPage();

			fireEvent.click(
				await screen.findByRole(
					"button",
					{ name: /View audit event artifact\.download/i },
					{ timeout: PAGE_TIMEOUT },
				),
			);

			const detail = await screen.findByTestId("audit-event-detail", {}, { timeout: PAGE_TIMEOUT });
			expect(within(detail).getByText("System")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"blocks access without view_audit",
		async () => {
			const me = buildAuthMe({
				active_organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
					role: "payroll_preparer",
					capabilities: ["view_master_data", "create_run"] as Capability[],
				},
			});
			const { handlers } = createAuthHandlers({ me });
			server.use(...handlers);

			renderAuditPage();

			expect(
				await screen.findByText("You don't have access", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.queryByTestId("audit-page")).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"renders empty state when there are no events",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("auditor"),
			});
			const { handlers: auditHandlers } = createAuditHandlers({ empty: true });
			server.use(...authHandlers, ...auditHandlers);

			renderAuditPage();

			expect(
				await screen.findByText("No audit events", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();
			expect(screen.getByText("No events match the current filters.")).toBeInTheDocument();
			expect(screen.queryByTestId("audit-detail-panel")).not.toBeInTheDocument();
			expect(screen.queryByText("Select an event")).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});
