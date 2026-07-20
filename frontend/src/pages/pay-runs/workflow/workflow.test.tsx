import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, AuthShellBoundary } from "@/contexts/AuthContext";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { buildAuthMe, buildRoleAuthMe, ROLE_CAPABILITIES } from "@/test/auth-fixtures";
import { createAuthHandlers } from "@/test/auth-handlers";
import { mockToast } from "@/test/helpers";
import { server } from "@/test/msw-server";
import type { Capability } from "@/types/auth";

import PayRunDetailPage from "../PayRunDetailPage";
import {
	buildCurrentVersion,
	buildRun,
	buildRunDetail,
	createPayRunHandlers,
} from "../pay-run-handlers";
import { ValidationFindingsPanel } from "./ValidationFindingsPanel";
import { WORKFLOW_ACTIONS } from "./workflow-actions";
import { buildFinding, createWorkflowHandlers } from "./workflow-handlers";

vi.mock("sonner", () => mockToast());

const PAGE_TIMEOUT = 15_000;

const ALL_CAPS: Capability[] = [
	"create_run",
	"submit_run",
	"approve_run",
	"post_run",
	"view_master_data",
];

function renderDetail(runId = "run-1") {
	return render(
		<QueryClientProvider client={queryClient}>
			<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME_TEST">
				<AuthProvider>
					<AuthShellBoundary>
						<MemoryRouter initialEntries={[`/pay-runs/${runId}`]}>
							<Routes>
								<Route path="/pay-runs/:runId" element={<PayRunDetailPage />} />
							</Routes>
						</MemoryRouter>
					</AuthShellBoundary>
				</AuthProvider>
			</ThemeProvider>
		</QueryClientProvider>,
	);
}

async function setupDetailPage(options: {
	status: string;
	capabilities?: Capability[];
	role?: "organization_administrator" | "payroll_preparer";
	workflow?: Parameters<typeof createWorkflowHandlers>[0];
	validateFindings?: ReturnType<typeof buildFinding>[];
}) {
	const capabilities =
		options.capabilities ??
		(options.role ? ROLE_CAPABILITIES[options.role] : ROLE_CAPABILITIES.organization_administrator);

	const me = buildAuthMe({
		organization: {
			id: "org-acme",
			name: "Acme Payroll",
			slug: "acme-payroll",
		},
		membership: {
			role: options.role ?? "organization_administrator",
			capabilities,
		},
	});

	const detail = buildRunDetail({
		id: "run-1",
		period_id: "period-1",
		period_year: 2026,
		period_month: 7,
		status: options.status,
		current_version: buildCurrentVersion({
			version_number: 2,
			content_hash: "hash-workflow-1",
			totals: {
				gross_total: "112000.00",
				deductions_total: "13000.00",
				net_payable: "99000.00",
			},
		}),
	});

	const pay = createPayRunHandlers({
		runs: [
			buildRun({
				id: "run-1",
				period_id: "period-1",
				period_year: 2026,
				period_month: 7,
				status: options.status,
			}),
		],
		details: { "run-1": detail },
	});

	const workflow = createWorkflowHandlers({
		details: pay.details,
		runs: pay.runs,
		validateResult: {
			findings: options.validateFindings ?? [],
			blocking: (options.validateFindings ?? []).some((f) => f.severity === "error"),
		},
		...options.workflow,
	});

	const { handlers: authHandlers } = createAuthHandlers({ me });
	server.use(...authHandlers, ...pay.handlers, ...workflow.handlers);

	renderDetail("run-1");
	expect(
		await screen.findByTestId("pay-run-detail-page", {}, { timeout: PAGE_TIMEOUT }),
	).toBeInTheDocument();

	return { pay, workflow };
}

describe("WorkflowActionBar visibility matrix", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	const cases: Array<{
		name: string;
		status: string;
		capabilities: Capability[];
		visible: string[];
		enabled: string[];
	}> = [
		{
			name: "calculated + preparer caps",
			status: "calculated",
			capabilities: ["create_run", "submit_run"],
			visible: ["validate", "submit"],
			enabled: ["validate", "submit"],
		},
		{
			name: "submitted + submit/approve",
			status: "submitted",
			capabilities: ["submit_run", "approve_run", "create_run"],
			visible: ["withdraw", "approve", "reject"],
			enabled: ["withdraw", "approve", "reject"],
		},
		{
			name: "approved + post",
			status: "approved",
			capabilities: ["post_run", "create_run"],
			visible: ["post"],
			enabled: ["post"],
		},
		{
			name: "posted + reverse",
			status: "posted",
			capabilities: ["post_run", "create_run"],
			visible: ["reverse"],
			enabled: ["reverse"],
		},
		{
			name: "calculated without submit",
			status: "calculated",
			capabilities: ["approve_run", "create_run"],
			visible: ["validate"],
			enabled: ["validate"],
		},
		{
			name: "draft disables all legal actions",
			status: "draft",
			capabilities: ALL_CAPS,
			visible: [],
			enabled: [],
		},
	];

	it.each(cases)(
		"$name",
		async ({ status, capabilities, visible, enabled }) => {
			const me = buildAuthMe({
				organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
				},
				membership: {
					role: "organization_administrator",
					capabilities,
				},
			});
			const { handlers: authHandlers } = createAuthHandlers({ me });
			const pay = createPayRunHandlers({
				details: {
					"run-1": buildRunDetail({
						id: "run-1",
						period_id: "period-1",
						period_year: 2026,
						period_month: 7,
						status,
						current_version: buildCurrentVersion(),
					}),
				},
				runs: [
					buildRun({
						id: "run-1",
						period_id: "period-1",
						period_year: 2026,
						period_month: 7,
						status,
					}),
				],
			});
			const workflow = createWorkflowHandlers({ details: pay.details, runs: pay.runs });
			server.use(...authHandlers, ...pay.handlers, ...workflow.handlers);

			renderDetail("run-1");
			if (visible.length > 0) {
				expect(
					await screen.findByTestId("workflow-action-bar", {}, { timeout: PAGE_TIMEOUT }),
				).toBeInTheDocument();
			} else {
				expect(
					await screen.findByTestId("pay-run-detail-page", {}, { timeout: PAGE_TIMEOUT }),
				).toBeInTheDocument();
				expect(screen.queryByTestId("workflow-action-bar")).not.toBeInTheDocument();
			}

			for (const actionId of WORKFLOW_ACTIONS.map((a) => a.id)) {
				const button = screen.queryByTestId(`workflow-action-${actionId}`);
				if (visible.includes(actionId)) {
					expect(button).toBeInTheDocument();
					if (enabled.includes(actionId)) {
						expect(button).toBeEnabled();
					} else {
						expect(button).toBeDisabled();
						expect(button).toHaveAttribute("title");
					}
				} else {
					expect(button).not.toBeInTheDocument();
				}
			}
		},
		PAGE_TIMEOUT,
	);

	it(
		"hides submit/approve/post without those capabilities",
		async () => {
			const me = buildAuthMe({
				organization: {
					id: "org-acme",
					name: "Acme Payroll",
					slug: "acme-payroll",
				},
				membership: {
					role: "auditor",
					capabilities: ["create_run", "view_audit"],
				},
			});
			const { handlers: authHandlers } = createAuthHandlers({ me });
			const pay = createPayRunHandlers({
				details: {
					"run-1": buildRunDetail({
						id: "run-1",
						period_id: "period-1",
						period_year: 2026,
						period_month: 7,
						status: "submitted",
						current_version: buildCurrentVersion(),
					}),
				},
			});
			server.use(...authHandlers, ...pay.handlers);

			renderDetail("run-1");
			expect(
				await screen.findByTestId("pay-run-detail-page", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();

			expect(screen.queryByTestId("workflow-action-validate")).not.toBeInTheDocument();
			expect(screen.queryByTestId("workflow-action-submit")).not.toBeInTheDocument();
			expect(screen.queryByTestId("workflow-action-approve")).not.toBeInTheDocument();
			expect(screen.queryByTestId("workflow-action-post")).not.toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});

describe("Workflow commands happy paths", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	async function confirmCommand(buttonTestId: string, options?: { reason?: string }) {
		fireEvent.click(screen.getByTestId(buttonTestId));
		expect(await screen.findByTestId("workflow-confirm-dialog")).toBeInTheDocument();
		if (options?.reason !== undefined) {
			fireEvent.change(screen.getByTestId("workflow-reason"), {
				target: { value: options.reason },
			});
		}
		fireEvent.click(screen.getByTestId("workflow-confirm-submit"));
	}

	it(
		"submit posts body + Idempotency-Key and invalidates status",
		async () => {
			const { toast } = await import("sonner");
			const captured: { body: unknown; key: string | null } = { body: null, key: null };
			await setupDetailPage({
				status: "calculated",
				workflow: {
					onSubmit: (_runId, body, headers) => {
						captured.body = body;
						captured.key = headers.get("Idempotency-Key");
					},
				},
			});

			await confirmCommand("workflow-action-submit", { reason: "Ready for review" });

			await waitFor(() => {
				expect(toast.success).toHaveBeenCalledWith("Pay run submitted");
			});
			expect(captured.body).toEqual({ reason: "Ready for review" });
			expect(captured.key).toBeTruthy();
			expect(await screen.findByText("Submitted")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"withdraw happy path",
		async () => {
			const { toast } = await import("sonner");
			let seen = false;
			await setupDetailPage({
				status: "submitted",
				workflow: {
					onWithdraw: () => {
						seen = true;
					},
				},
			});

			await confirmCommand("workflow-action-withdraw");
			await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Pay run withdrawn"));
			expect(seen).toBe(true);
			expect(await screen.findByText("Calculated")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"approve happy path",
		async () => {
			const { toast } = await import("sonner");
			let body: unknown = null;
			await setupDetailPage({
				status: "submitted",
				workflow: {
					onApprove: (_id, requestBody) => {
						body = requestBody;
					},
				},
			});
			await confirmCommand("workflow-action-approve", { reason: "Looks good" });
			await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Pay run approved"));
			expect(body).toEqual({ reason: "Looks good" });
			expect(await screen.findByText("Approved")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"reject happy path",
		async () => {
			const { toast } = await import("sonner");
			await setupDetailPage({ status: "submitted" });
			await confirmCommand("workflow-action-reject", { reason: "Fix deductions" });
			await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Pay run rejected"));
			expect(await screen.findByText("Rejected")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"post shows summary and posts with Idempotency-Key",
		async () => {
			const { toast } = await import("sonner");
			let key: string | null = null;
			await setupDetailPage({
				status: "approved",
				workflow: {
					onPost: (_id, headers) => {
						key = headers.get("Idempotency-Key");
					},
				},
			});

			fireEvent.click(screen.getByTestId("workflow-action-post"));
			const dialog = await screen.findByTestId("workflow-confirm-dialog");
			expect(within(dialog).getByTestId("post-summary")).toBeInTheDocument();
			expect(within(dialog).getByText(/irreversible/i)).toBeInTheDocument();
			expect(within(dialog).getByText("hash-workflow-1")).toBeInTheDocument();
			fireEvent.click(screen.getByTestId("workflow-confirm-submit"));

			await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Pay run posted"));
			expect(key).toBeTruthy();
			expect(await screen.findByText("Posted")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"reverse requires reason client-side",
		async () => {
			await setupDetailPage({ status: "posted" });

			fireEvent.click(screen.getByTestId("workflow-action-reverse"));
			expect(await screen.findByTestId("workflow-confirm-dialog")).toBeInTheDocument();
			fireEvent.click(screen.getByTestId("workflow-confirm-submit"));

			expect(await screen.findByTestId("workflow-dialog-error")).toHaveTextContent(
				/reason is required/i,
			);
			expect(screen.getByTestId("workflow-confirm-dialog")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"reverse happy path with reason + Idempotency-Key",
		async () => {
			const { toast } = await import("sonner");
			const captured: { body: unknown; key: string | null } = { body: null, key: null };
			await setupDetailPage({
				status: "posted",
				workflow: {
					onReverse: (_id, body, headers) => {
						captured.body = body;
						captured.key = headers.get("Idempotency-Key");
					},
				},
			});

			await confirmCommand("workflow-action-reverse", { reason: "Correction required" });
			await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Pay run reversed"));
			expect(captured.body).toEqual({ reason: "Correction required" });
			expect(captured.key).toBeTruthy();
			expect(await screen.findByText("Reversed")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);
});

describe("Workflow 409 handling", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"maker/checker 409 shows inline alert",
		async () => {
			await setupDetailPage({
				status: "submitted",
				workflow: {
					commandErrors: {
						approve: {
							status: 409,
							body: {
								detail: "Maker cannot approve their own submission",
								error: "urn:accord:workflow:maker_checker",
							},
						},
					},
				},
			});

			fireEvent.click(screen.getByTestId("workflow-action-approve"));
			expect(await screen.findByTestId("workflow-confirm-dialog")).toBeInTheDocument();
			fireEvent.click(screen.getByTestId("workflow-confirm-submit"));

			expect(await screen.findByTestId("maker-checker-alert")).toHaveTextContent(
				"You submitted this run; a different reviewer must approve it",
			);
		},
		PAGE_TIMEOUT,
	);

	it(
		"stale_version 409 shows refresh prompt",
		async () => {
			await setupDetailPage({
				status: "submitted",
				workflow: {
					commandErrors: {
						approve: {
							status: 409,
							body: {
								detail: "Version is stale",
								error: "urn:accord:workflow:stale_version",
							},
						},
					},
				},
			});

			fireEvent.click(screen.getByTestId("workflow-action-approve"));
			expect(await screen.findByTestId("workflow-confirm-dialog")).toBeInTheDocument();
			fireEvent.click(screen.getByTestId("workflow-confirm-submit"));

			expect(await screen.findByTestId("stale-version-alert")).toBeInTheDocument();
			expect(screen.getByTestId("stale-refresh-button")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it(
		"other 409s toast problem detail",
		async () => {
			const { toast } = await import("sonner");
			await setupDetailPage({
				status: "calculated",
				workflow: {
					commandErrors: {
						submit: {
							status: 409,
							body: {
								detail: "Illegal transition",
								error: "urn:accord:workflow:illegal_transition",
							},
						},
					},
				},
			});

			fireEvent.click(screen.getByTestId("workflow-action-submit"));
			expect(await screen.findByTestId("workflow-confirm-dialog")).toBeInTheDocument();
			fireEvent.click(screen.getByTestId("workflow-confirm-submit"));

			await waitFor(() => {
				expect(toast.error).toHaveBeenCalledWith("Illegal transition");
			});
		},
		PAGE_TIMEOUT,
	);
});

describe("Validation Findings panel", () => {
	beforeEach(() => {
		queryClient.clear();
	});

	it(
		"validate renders findings; errors block, warnings do not",
		async () => {
			await setupDetailPage({
				status: "calculated",
				validateFindings: [
					buildFinding({
						code: "duplicate_component_code",
						severity: "error",
						employee_ref: "emp-1",
						component_code: "BASIC",
						message: "Duplicate BASIC",
					}),
					buildFinding({
						code: "zero_net_payable",
						severity: "warning",
						employee_ref: "emp-2",
						message: "Zero net",
					}),
					buildFinding({
						code: "info_note",
						severity: "info",
						message: "FYI",
					}),
				],
			});

			fireEvent.click(screen.getByTestId("workflow-action-validate"));

			expect(await screen.findByTestId("validation-findings-panel")).toBeInTheDocument();
			expect(screen.getByTestId("validation-blocking-banner")).toBeInTheDocument();
			expect(screen.getByTestId("findings-group-error")).toBeInTheDocument();
			expect(screen.getByTestId("findings-group-warning")).toBeInTheDocument();
			expect(screen.getByTestId("findings-group-info")).toBeInTheDocument();
			expect(screen.getByText("Employee emp-1 · Component BASIC")).toBeInTheDocument();
		},
		PAGE_TIMEOUT,
	);

	it("warnings alone do not show blocking banner", () => {
		render(
			<ValidationFindingsPanel
				result={{
					id: "run-1",
					status: "calculated",
					current_version_number: 1,
					content_hash: "hash",
					blocking: false,
					findings: [
						buildFinding({
							code: "zero_net_payable",
							severity: "warning",
							message: "Zero net",
						}),
					],
				}}
			/>,
		);

		expect(screen.getByTestId("validation-findings-panel")).toBeInTheDocument();
		expect(screen.queryByTestId("validation-blocking-banner")).not.toBeInTheDocument();
		expect(screen.getByTestId("findings-group-warning")).toBeInTheDocument();
	});

	it(
		"findings clear when run is recalculated",
		async () => {
			const { handlers: authHandlers } = createAuthHandlers({
				me: buildRoleAuthMe("organization_administrator"),
			});
			const pay = createPayRunHandlers({
				runs: [
					buildRun({
						id: "run-1",
						period_id: "period-1",
						period_year: 2026,
						period_month: 7,
						status: "calculated",
					}),
				],
				details: {
					"run-1": buildRunDetail({
						id: "run-1",
						period_id: "period-1",
						period_year: 2026,
						period_month: 7,
						status: "calculated",
						current_version: buildCurrentVersion(),
					}),
				},
			});
			const workflow = createWorkflowHandlers({
				details: pay.details,
				runs: pay.runs,
				validateResult: {
					findings: [
						buildFinding({
							code: "zero_net_payable",
							severity: "warning",
							message: "Zero net",
						}),
					],
					blocking: false,
				},
			});
			server.use(...authHandlers, ...pay.handlers, ...workflow.handlers);

			renderDetail("run-1");
			expect(
				await screen.findByTestId("workflow-action-bar", {}, { timeout: PAGE_TIMEOUT }),
			).toBeInTheDocument();

			fireEvent.click(screen.getByTestId("workflow-action-validate"));
			expect(await screen.findByTestId("validation-findings-panel")).toBeInTheDocument();

			fireEvent.click(screen.getByRole("button", { name: "Calculate Pay Run" }));
			await waitFor(() => {
				expect(screen.queryByTestId("validation-findings-panel")).not.toBeInTheDocument();
			});
		},
		PAGE_TIMEOUT,
	);
});
