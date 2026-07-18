import { type FormEvent, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
	formatCanonicalMoney,
	type PayrollRunCalculateResult,
	type PayrollRunTotals,
} from "@/lib/api/payroll-runs";

import type { WorkflowActionId } from "./workflow-actions";

export type WorkflowConfirmCommand =
	| "submit"
	| "withdraw"
	| "approve"
	| "reject"
	| "post"
	| "reverse";

type WorkflowConfirmDialogProps = {
	open: boolean;
	command: WorkflowConfirmCommand | null;
	onOpenChange: (open: boolean) => void;
	onConfirm: (payload: { reason: string | null; idempotencyKey: string }) => void | Promise<void>;
	isPending?: boolean;
	versionInfo?: PayrollRunCalculateResult | null;
	formError?: string | null;
};

const TITLES: Record<WorkflowConfirmCommand, string> = {
	submit: "Submit pay run?",
	withdraw: "Withdraw pay run?",
	approve: "Approve pay run?",
	reject: "Reject pay run?",
	post: "Post pay run?",
	reverse: "Reverse pay run?",
};

const DESCRIPTIONS: Record<WorkflowConfirmCommand, string> = {
	submit: "Submit this calculated run for review. An optional reason is recorded with the action.",
	withdraw: "Withdraw this submission and return the run to calculated status.",
	approve: "Approve this submitted run so it can be posted.",
	reject: "Reject this submitted run and return it for correction.",
	post: "Posting locks this run permanently. Posted results cannot be edited in place.",
	reverse:
		"Create a reversal run for this posted payroll. A reason is required for the audit trail.",
};

const CONFIRM_LABELS: Record<WorkflowConfirmCommand, string> = {
	submit: "Submit",
	withdraw: "Withdraw",
	approve: "Approve",
	reject: "Reject",
	post: "Post permanently",
	reverse: "Reverse",
};

const TOTAL_KEYS: Array<{ key: keyof PayrollRunTotals; label: string }> = [
	{ key: "gross_total", label: "Gross" },
	{ key: "deductions_total", label: "Deductions" },
	{ key: "net_payable", label: "Net payable" },
];

function newIdempotencyKey(): string {
	return crypto.randomUUID();
}

export function isConfirmCommand(actionId: WorkflowActionId): actionId is WorkflowConfirmCommand {
	return actionId !== "validate";
}

export function WorkflowConfirmDialog({
	open,
	command,
	onOpenChange,
	onConfirm,
	isPending = false,
	versionInfo = null,
	formError = null,
}: WorkflowConfirmDialogProps) {
	const [reason, setReason] = useState("");
	const [clientError, setClientError] = useState<string | null>(null);
	const [idempotencyKey, setIdempotencyKey] = useState(newIdempotencyKey);

	useEffect(() => {
		if (open) {
			setReason("");
			setClientError(null);
			setIdempotencyKey(newIdempotencyKey());
		}
	}, [open]);

	const reasonRequired = command === "reverse";
	const showReasonField = command != null && command !== "post";

	const postSummary = useMemo(() => {
		if (command !== "post" || !versionInfo) return null;
		return versionInfo;
	}, [command, versionInfo]);

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		if (!command) return;
		setClientError(null);

		const trimmed = reason.trim();
		if (reasonRequired && !trimmed) {
			setClientError("A reason is required to reverse a posted pay run.");
			return;
		}

		await onConfirm({
			reason: showReasonField ? trimmed || null : null,
			idempotencyKey,
		});
	};

	if (!command) return null;

	const displayError = clientError ?? formError;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-md" data-testid="workflow-confirm-dialog">
				<DialogHeader>
					<DialogTitle>{TITLES[command]}</DialogTitle>
					<DialogDescription>{DESCRIPTIONS[command]}</DialogDescription>
				</DialogHeader>

				<form className="grid gap-4" onSubmit={(event) => void handleSubmit(event)}>
					{postSummary ? (
						<div
							className="grid gap-2 rounded-md border border-border bg-muted/30 p-3 text-sm"
							data-testid="post-summary"
						>
							<p className="font-medium text-foreground">
								This action is irreversible. Posted pay runs cannot be mutated in place.
							</p>
							<dl className="grid gap-1 text-muted-foreground">
								<div className="flex justify-between gap-4">
									<dt>Version</dt>
									<dd className="font-medium text-foreground">v{postSummary.version_number}</dd>
								</div>
								<div className="flex justify-between gap-4">
									<dt>Content hash</dt>
									<dd
										className="truncate font-mono text-xs text-foreground"
										title={postSummary.content_hash}
									>
										{postSummary.content_hash}
									</dd>
								</div>
								{TOTAL_KEYS.filter((item) => postSummary.totals[item.key]).map((item) => (
									<div key={item.key} className="flex justify-between gap-4">
										<dt>{item.label}</dt>
										<dd className="font-medium text-foreground">
											{formatCanonicalMoney(postSummary.totals[item.key])}
										</dd>
									</div>
								))}
							</dl>
						</div>
					) : null}

					{showReasonField ? (
						<div className="grid gap-2">
							<Label htmlFor="workflow-reason">
								Reason{reasonRequired ? " (required)" : " (optional)"}
							</Label>
							<Textarea
								id="workflow-reason"
								value={reason}
								onChange={(event) => setReason(event.target.value)}
								disabled={isPending}
								aria-required={reasonRequired}
								data-testid="workflow-reason"
							/>
						</div>
					) : null}

					{displayError ? (
						<p
							className="text-sm text-destructive"
							role="alert"
							data-testid="workflow-dialog-error"
						>
							{displayError}
						</p>
					) : null}

					<input type="hidden" name="idempotencyKey" value={idempotencyKey} readOnly />

					<DialogFooter>
						<Button
							type="button"
							variant="outline"
							onClick={() => onOpenChange(false)}
							disabled={isPending}
						>
							Cancel
						</Button>
						<Button
							type="submit"
							variant={command === "reject" || command === "reverse" ? "destructive" : "default"}
							disabled={isPending}
							data-testid="workflow-confirm-submit"
						>
							{isPending ? "Working…" : CONFIRM_LABELS[command]}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
