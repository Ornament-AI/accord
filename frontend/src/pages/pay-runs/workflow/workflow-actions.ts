import type { Capability } from "@/types/auth";

export type WorkflowActionId =
	| "validate"
	| "submit"
	| "withdraw"
	| "approve"
	| "reject"
	| "post"
	| "reverse";

export type WorkflowActionDef = {
	id: WorkflowActionId;
	label: string;
	capability: Capability;
	/** Statuses where the action is enabled. */
	legalStatuses: readonly string[];
	variant?: "default" | "outline" | "destructive" | "secondary";
};

export const WORKFLOW_ACTIONS: readonly WorkflowActionDef[] = [
	{
		id: "validate",
		label: "Validate",
		capability: "create_run",
		legalStatuses: ["calculated"],
		variant: "outline",
	},
	{
		id: "submit",
		label: "Submit",
		capability: "submit_run",
		legalStatuses: ["calculated"],
	},
	{
		id: "withdraw",
		label: "Withdraw",
		capability: "submit_run",
		legalStatuses: ["submitted"],
		variant: "outline",
	},
	{
		id: "approve",
		label: "Approve",
		capability: "approve_run",
		legalStatuses: ["submitted"],
	},
	{
		id: "reject",
		label: "Reject",
		capability: "approve_run",
		legalStatuses: ["submitted"],
		variant: "destructive",
	},
	{
		id: "post",
		label: "Post",
		capability: "post_run",
		legalStatuses: ["approved"],
	},
	{
		id: "reverse",
		label: "Reverse",
		capability: "post_run",
		legalStatuses: ["posted"],
		variant: "destructive",
	},
] as const;

export function isWorkflowActionLegal(actionId: WorkflowActionId, status: string): boolean {
	const action = WORKFLOW_ACTIONS.find((item) => item.id === actionId);
	return action ? action.legalStatuses.includes(status) : false;
}

export function workflowActionDisabledReason(
	action: WorkflowActionDef,
	status: string,
): string | null {
	if (action.legalStatuses.includes(status)) return null;
	const allowed = action.legalStatuses.join(", ");
	return `${action.label} is only available when status is ${allowed} (current: ${status}).`;
}

export const WORKFLOW_URN_MAKER_CHECKER = "urn:accord:workflow:maker_checker";
export const WORKFLOW_URN_STALE_VERSION = "urn:accord:workflow:stale_version";

export function getWorkflowErrorUrn(error: unknown): string | null {
	if (!error || typeof error !== "object") return null;
	const record = error as { code?: unknown; detail?: unknown; message?: unknown };
	const candidates = [record.code, record.detail, record.message];
	for (const candidate of candidates) {
		if (typeof candidate === "string" && candidate.includes("urn:accord:workflow:")) {
			const match = candidate.match(/urn:accord:workflow:[a-z_]+/);
			if (match) return match[0];
		}
	}
	return null;
}
