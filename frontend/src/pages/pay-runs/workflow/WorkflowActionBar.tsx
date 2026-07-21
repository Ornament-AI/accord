import { Fragment, type ReactNode, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import {
	type PayrollRunValidateResult,
	useApprovePayrollRun,
	usePostPayrollRun,
	useRejectPayrollRun,
	useReversePayrollRun,
	useSubmitPayrollRun,
	useValidatePayrollRun,
	useWithdrawPayrollRun,
} from "@/lib/api/payroll-run-workflow";
import type { PayrollRunCalculateResult, PayrollRunDetail } from "@/lib/api/payroll-runs";
import { ApiError, getErrorMessage } from "@/lib/errors";

import {
	isConfirmCommand,
	type WorkflowConfirmCommand,
	WorkflowConfirmDialog,
} from "./WorkflowConfirmDialog";
import {
	getWorkflowErrorUrn,
	WORKFLOW_ACTIONS,
	WORKFLOW_URN_MAKER_CHECKER,
	WORKFLOW_URN_STALE_VERSION,
	workflowActionDisabledReason,
} from "./workflow-actions";

type WorkflowActionBarProps = {
	run: PayrollRunDetail;
	versionInfo?: PayrollRunCalculateResult | null;
	onValidated: (result: PayrollRunValidateResult) => void;
	onRefresh?: () => void;
	/** Inserted before Submit when present; otherwise after other workflow actions. */
	children?: ReactNode;
};

export function WorkflowActionBar({
	run,
	versionInfo = null,
	onValidated,
	onRefresh,
	children = null,
}: WorkflowActionBarProps) {
	const { hasCapability } = useAuth();
	const [confirmCommand, setConfirmCommand] = useState<WorkflowConfirmCommand | null>(null);
	const [dialogError, setDialogError] = useState<string | null>(null);
	const [makerCheckerAlert, setMakerCheckerAlert] = useState(false);
	const [staleAlert, setStaleAlert] = useState(false);

	const validateMutation = useValidatePayrollRun(run.id);
	const submitMutation = useSubmitPayrollRun(run.id);
	const withdrawMutation = useWithdrawPayrollRun(run.id);
	const approveMutation = useApprovePayrollRun(run.id);
	const rejectMutation = useRejectPayrollRun(run.id);
	const postMutation = usePostPayrollRun(run.id);
	const reverseMutation = useReversePayrollRun(run.id);

	const anyPending =
		validateMutation.isPending ||
		submitMutation.isPending ||
		withdrawMutation.isPending ||
		approveMutation.isPending ||
		rejectMutation.isPending ||
		postMutation.isPending ||
		reverseMutation.isPending;

	const visibleActions = WORKFLOW_ACTIONS.filter(
		(action) => hasCapability(action.capability) && action.legalStatuses.includes(run.status),
	);

	const handleWorkflowError = (error: unknown) => {
		const urn = getWorkflowErrorUrn(error);
		if (urn === WORKFLOW_URN_MAKER_CHECKER) {
			setMakerCheckerAlert(true);
			setStaleAlert(false);
			return;
		}
		if (urn === WORKFLOW_URN_STALE_VERSION) {
			setStaleAlert(true);
			setMakerCheckerAlert(false);
			return;
		}
		if (error instanceof ApiError && error.status === 409) {
			toast.error(error.detail || getErrorMessage(error, "Workflow conflict."));
			return;
		}
		toast.error(getErrorMessage(error, "Workflow command failed."));
	};

	const handleValidate = async () => {
		setMakerCheckerAlert(false);
		setStaleAlert(false);
		try {
			const result = await validateMutation.mutateAsync();
			onValidated(result);
			if (result.blocking) {
				toast.error("Validation found blocking errors.");
			} else if (result.findings.length === 0) {
				toast.success("Validation passed with no findings.");
			} else {
				toast.success("Validation completed.");
			}
		} catch (error) {
			handleWorkflowError(error);
		}
	};

	const openConfirm = (command: WorkflowConfirmCommand) => {
		setDialogError(null);
		setMakerCheckerAlert(false);
		setStaleAlert(false);
		setConfirmCommand(command);
	};

	const handleConfirm = async ({
		reason,
		idempotencyKey,
	}: {
		reason: string | null;
		idempotencyKey: string;
	}) => {
		if (!confirmCommand) return;
		setDialogError(null);

		try {
			switch (confirmCommand) {
				case "submit":
					await submitMutation.mutateAsync({ idempotencyKey, reason });
					toast.success("Pay run submitted");
					break;
				case "withdraw":
					await withdrawMutation.mutateAsync({ idempotencyKey, reason });
					toast.success("Pay run withdrawn");
					break;
				case "approve":
					await approveMutation.mutateAsync({ idempotencyKey, reason });
					toast.success("Pay run approved");
					break;
				case "reject":
					await rejectMutation.mutateAsync({ idempotencyKey, reason });
					toast.success("Pay run rejected");
					break;
				case "post":
					await postMutation.mutateAsync(idempotencyKey);
					toast.success("Pay run posted");
					break;
				case "reverse":
					await reverseMutation.mutateAsync({
						idempotencyKey,
						reason: reason ?? "",
					});
					toast.success("Pay run reversed");
					break;
			}
			setConfirmCommand(null);
		} catch (error) {
			const urn = getWorkflowErrorUrn(error);
			if (urn === WORKFLOW_URN_MAKER_CHECKER || urn === WORKFLOW_URN_STALE_VERSION) {
				setConfirmCommand(null);
				handleWorkflowError(error);
				return;
			}
			if (error instanceof ApiError && error.status === 409) {
				setConfirmCommand(null);
				handleWorkflowError(error);
				return;
			}
			setDialogError(getErrorMessage(error, "Workflow command failed."));
		}
	};

	const handleActionClick = (actionId: (typeof WORKFLOW_ACTIONS)[number]["id"]) => {
		if (actionId === "validate") {
			void handleValidate();
			return;
		}
		if (isConfirmCommand(actionId)) {
			openConfirm(actionId);
		}
	};

	const submitVisible = visibleActions.some((action) => action.id === "submit");

	if (visibleActions.length === 0) {
		return children ? <div className="flex flex-wrap items-center gap-2">{children}</div> : null;
	}

	const actionButtons = (
		<div className="flex flex-wrap items-center gap-2" data-testid="workflow-action-bar">
			{visibleActions.map((action) => {
				const disabledReason = workflowActionDisabledReason(action, run.status);
				const disabled = Boolean(disabledReason) || anyPending;
				return (
					<Fragment key={action.id}>
						{action.id === "submit" ? children : null}
						<Button
							type="button"
							size="xs"
							variant={action.variant ?? "default"}
							disabled={disabled}
							title={disabledReason ?? undefined}
							aria-label={`${action.label} pay run`}
							data-testid={`workflow-action-${action.id}`}
							onClick={() => handleActionClick(action.id)}
						>
							{action.id === "validate" && validateMutation.isPending
								? "Validating…"
								: action.label}
						</Button>
					</Fragment>
				);
			})}
			{!submitVisible ? children : null}
		</div>
	);

	const alerts = (
		<>
			{makerCheckerAlert ? (
				<Alert variant="destructive" data-testid="maker-checker-alert">
					<AlertTitle>Maker/checker conflict</AlertTitle>
					<AlertDescription>
						You submitted this run; a different reviewer must approve it.
					</AlertDescription>
				</Alert>
			) : null}

			{staleAlert ? (
				<Alert variant="warning" data-testid="stale-version-alert">
					<AlertTitle>Run Is Out of Date</AlertTitle>
					<AlertDescription className="flex flex-wrap items-center gap-3">
						<span>This run changed since you loaded it. Refresh to see the latest version.</span>
						<Button
							type="button"
							size="xs"
							variant="outline"
							onClick={() => {
								setStaleAlert(false);
								onRefresh?.();
							}}
							data-testid="stale-refresh-button"
						>
							Refresh
						</Button>
					</AlertDescription>
				</Alert>
			) : null}
		</>
	);

	return (
		<>
			{makerCheckerAlert || staleAlert ? (
				<div className="grid gap-3">
					{alerts}
					{actionButtons}
				</div>
			) : (
				actionButtons
			)}

			<WorkflowConfirmDialog
				open={Boolean(confirmCommand)}
				command={confirmCommand}
				onOpenChange={(open) => {
					if (!open) {
						setConfirmCommand(null);
						setDialogError(null);
					}
				}}
				onConfirm={handleConfirm}
				isPending={anyPending}
				versionInfo={versionInfo}
				formError={dialogError}
			/>
		</>
	);
}
