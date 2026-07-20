import { type FormEvent, useEffect, useState } from "react";
import { PageSkeleton } from "@/components/page-skeleton";
import { isInteractiveRowTarget } from "@/components/table-interactions";
import { Button } from "@/components/ui/button";
import {
	DatePicker,
	HISTORICAL_DATE_CALENDAR_PROPS,
	SCHEDULABLE_DATE_CALENDAR_PROPS,
} from "@/components/ui/date-picker";
import {
	Dialog,
	DialogBody,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { parseApiDate, toApiDate } from "@/lib/api/employees";
import {
	ADVANCE_TYPES,
	type AdvanceResponse,
	type AdvanceType,
	advanceTypeLabel,
	useAdvances,
	useCreateAdvance,
	useCreateAdvanceInstallmentVersion,
} from "@/lib/api/pay-setup";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { ApiError, getErrorMessage } from "@/lib/errors";
import { formatDate } from "@/lib/utils";

import { parseMoneyString, validatePositiveMoney } from "./money";

type AdvancesTabProps = {
	employeeId: string;
	asOf: string;
	canManage: boolean;
	createOpen: boolean;
	onCreateOpenChange: (open: boolean) => void;
};

function formatProgress(row: AdvanceResponse): string {
	const recovered = row.installments_recovered_opening;
	const total = row.installments_total;
	if (recovered == null || total == null) return "—";
	return `${recovered}/${total}`;
}

export function AdvancesTab({
	employeeId,
	asOf,
	canManage,
	createOpen,
	onCreateOpenChange,
}: AdvancesTabProps) {
	const advancesQuery = useAdvances(employeeId, asOf);
	const [versionTarget, setVersionTarget] = useState<AdvanceResponse | null>(null);

	const rows = advancesQuery.data ?? [];

	return (
		<div className="grid gap-4" data-testid="advances-tab">
			{advancesQuery.isLoading ? <PageSkeleton /> : null}

			{advancesQuery.isError ? (
				<ErrorWithRetry
					message={getErrorMessage(advancesQuery.error, "Failed to load advances.")}
					onRetry={() => void advancesQuery.refetch()}
				/>
			) : null}

			{!advancesQuery.isLoading && !advancesQuery.isError ? (
				rows.length === 0 ? (
					<p className="text-sm text-muted-foreground">No advances as of this date.</p>
				) : (
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>Type</TableHead>
								<TableHead className="text-right">Principal</TableHead>
								<TableHead>Sanctioned On</TableHead>
								<TableHead className="text-right">Installment</TableHead>
								<TableHead className="text-right">Progress</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{rows.map((row) => (
								<TableRow
									key={row.id}
									className={canManage ? "cursor-pointer" : undefined}
									onClick={(event) => {
										if (!canManage || isInteractiveRowTarget(event.target, event.currentTarget)) {
											return;
										}
										setVersionTarget(row);
									}}
								>
									<TableCell>
										{canManage ? (
											<button
												type="button"
												className="sr-only focus:not-sr-only focus:mb-1 focus:inline-flex focus:rounded-md focus:bg-background focus:px-2 focus:py-1 focus:ring-2 focus:ring-ring/35"
												onClick={() => setVersionTarget(row)}
											>
												Update Installment
											</button>
										) : null}
										{advanceTypeLabel(row.advance_type)}
									</TableCell>
									<TableCell className="text-right">{row.principal}</TableCell>
									<TableCell>{formatDate(row.sanctioned_on)}</TableCell>
									<TableCell className="text-right">{row.installment_amount ?? "—"}</TableCell>
									<TableCell className="text-right">{formatProgress(row)}</TableCell>
								</TableRow>
							))}
						</TableBody>
					</Table>
				)
			) : null}

			{canManage ? (
				<>
					<AddAdvanceDialog
						open={createOpen}
						onOpenChange={onCreateOpenChange}
						employeeId={employeeId}
					/>
					<NewInstallmentVersionDialog
						open={Boolean(versionTarget)}
						onOpenChange={(open) => {
							if (!open) setVersionTarget(null);
						}}
						employeeId={employeeId}
						advance={versionTarget}
					/>
				</>
			) : null}
		</div>
	);
}

function validateInstallmentFields(args: {
	principal: string;
	installmentAmount: string;
	recoveredOpening: string;
	total: string;
}): string | null {
	const principalError = validatePositiveMoney(args.principal, "Principal");
	if (principalError) return principalError;

	const installmentError = validatePositiveMoney(args.installmentAmount, "Installment Amount");
	if (installmentError) return installmentError;

	const principal = parseMoneyString(args.principal.trim());
	const installment = parseMoneyString(args.installmentAmount.trim());
	if (principal !== null && installment !== null && installment > principal) {
		return "Installment amount must be less than or equal to principal.";
	}

	const recovered = Number(args.recoveredOpening);
	const total = Number(args.total);
	if (!Number.isInteger(recovered) || recovered < 0) {
		return "Installments recovered opening must be a non-negative integer.";
	}
	if (!Number.isInteger(total) || total <= 0) {
		return "Installments Total must be a positive integer.";
	}
	if (recovered > total) {
		return "Installments recovered opening must be less than or equal to installments total.";
	}
	return null;
}

type AddAdvanceForm = {
	advance_type: AdvanceType;
	principal: string;
	sanctioned_on: string;
	reference: string;
	effective_from: string;
	installment_amount: string;
	installments_recovered_opening: string;
	installments_total: string;
	change_reason: string;
};

const emptyAddForm = (): AddAdvanceForm => ({
	advance_type: "hba",
	principal: "",
	sanctioned_on: "",
	reference: "",
	effective_from: "",
	installment_amount: "",
	installments_recovered_opening: "0",
	installments_total: "",
	change_reason: "",
});

function AddAdvanceDialog({
	open,
	onOpenChange,
	employeeId,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	employeeId: string;
}) {
	const createAdvance = useCreateAdvance(employeeId);
	const [form, setForm] = useState<AddAdvanceForm>(emptyAddForm);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyAddForm());
			setFormError(null);
		}
	}, [open]);

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setFormError(null);

		if (!form.sanctioned_on) {
			setFormError("Sanctioned on is required.");
			return;
		}
		if (!form.effective_from) {
			setFormError("Installment effective from is required.");
			return;
		}

		const validationError = validateInstallmentFields({
			principal: form.principal,
			installmentAmount: form.installment_amount,
			recoveredOpening: form.installments_recovered_opening,
			total: form.installments_total,
		});
		if (validationError) {
			setFormError(validationError);
			return;
		}

		try {
			await createAdvance.mutateAsync({
				advance_type: form.advance_type,
				principal: form.principal.trim(),
				sanctioned_on: form.sanctioned_on,
				reference: form.reference.trim() || null,
				installment: {
					effective_from: form.effective_from,
					installment_amount: form.installment_amount.trim(),
					installments_recovered_opening: Number(form.installments_recovered_opening),
					installments_total: Number(form.installments_total),
				},
			});
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 422) {
				setFormError(error.detail || "Validation failed.");
				return;
			}
			setFormError(getErrorMessage(error, "Failed to create advance."));
		}
	};

	const isSubmitting = createAdvance.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.form}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>Add Advance</DialogTitle>
					<DialogDescription>
						Record an advance and its first installment schedule for this employee.
					</DialogDescription>
				</DialogHeader>

				<form
					className="flex min-h-0 flex-1 flex-col"
					onSubmit={(event) => void handleSubmit(event)}
					data-testid="add-advance-form"
				>
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="add-adv-type">Type</Label>
							<Select
								value={form.advance_type}
								onValueChange={(value) =>
									setForm((prev) => ({ ...prev, advance_type: value as AdvanceType }))
								}
								disabled={isSubmitting}
							>
								<SelectTrigger id="add-adv-type" className="w-full">
									<SelectValue>
										{(value: AdvanceType | null) =>
											value ? advanceTypeLabel(value) : "Select advance type"
										}
									</SelectValue>
								</SelectTrigger>
								<SelectContent>
									{ADVANCE_TYPES.map((type) => (
										<SelectItem key={type} value={type}>
											{advanceTypeLabel(type)}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-adv-principal">Principal</Label>
							<Input
								id="add-adv-principal"
								inputMode="decimal"
								value={form.principal}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, principal: event.target.value }))
								}
								disabled={isSubmitting}
								placeholder="0.00"
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-adv-sanctioned-on">Sanctioned On</Label>
							<DatePicker
								id="add-adv-sanctioned-on"
								value={form.sanctioned_on ? parseApiDate(form.sanctioned_on) : undefined}
								onValueChange={(date) =>
									setForm((prev) => ({
										...prev,
										sanctioned_on: date ? toApiDate(date) : "",
									}))
								}
								disabled={isSubmitting}
								className="w-full"
								placeholder="Sanctioned On"
								calendarProps={HISTORICAL_DATE_CALENDAR_PROPS}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-adv-reference">Reference (Optional)</Label>
							<Input
								id="add-adv-reference"
								value={form.reference}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, reference: event.target.value }))
								}
								disabled={isSubmitting}
							/>
						</div>

						<fieldset className="grid gap-3 rounded-md border p-3">
							<legend className="px-1 text-sm font-medium">First Installment</legend>

							<div className="grid gap-2">
								<Label htmlFor="add-adv-inst-from">Effective From</Label>
								<DatePicker
									id="add-adv-inst-from"
									value={form.effective_from ? parseApiDate(form.effective_from) : undefined}
									onValueChange={(date) =>
										setForm((prev) => ({
											...prev,
											effective_from: date ? toApiDate(date) : "",
										}))
									}
									disabled={isSubmitting}
									className="w-full"
									placeholder="Effective From"
									calendarProps={SCHEDULABLE_DATE_CALENDAR_PROPS}
								/>
							</div>

							<div className="grid gap-2">
								<Label htmlFor="add-adv-inst-amount">Installment Amount</Label>
								<Input
									id="add-adv-inst-amount"
									inputMode="decimal"
									value={form.installment_amount}
									onChange={(event) =>
										setForm((prev) => ({ ...prev, installment_amount: event.target.value }))
									}
									disabled={isSubmitting}
									placeholder="0.00"
								/>
							</div>

							<div className="grid gap-2">
								<Label htmlFor="add-adv-inst-recovered">Installments Recovered (Opening)</Label>
								<Input
									id="add-adv-inst-recovered"
									type="number"
									min={0}
									step={1}
									value={form.installments_recovered_opening}
									onChange={(event) =>
										setForm((prev) => ({
											...prev,
											installments_recovered_opening: event.target.value,
										}))
									}
									disabled={isSubmitting}
								/>
							</div>

							<div className="grid gap-2">
								<Label htmlFor="add-adv-inst-total">Installments Total</Label>
								<Input
									id="add-adv-inst-total"
									type="number"
									min={1}
									step={1}
									value={form.installments_total}
									onChange={(event) =>
										setForm((prev) => ({ ...prev, installments_total: event.target.value }))
									}
									disabled={isSubmitting}
								/>
							</div>
						</fieldset>

						{formError ? (
							<p className="text-sm text-destructive" role="alert" data-testid="advance-form-error">
								{formError}
							</p>
						) : null}
					</DialogBody>

					<DialogFooter className="border-t px-6 py-4">
						<Button
							type="button"
							variant="outline"
							onClick={() => onOpenChange(false)}
							disabled={isSubmitting}
						>
							Cancel
						</Button>
						<Button type="submit" disabled={isSubmitting}>
							{isSubmitting ? "Creating…" : "Add"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

type InstallmentVersionForm = {
	effective_from: string;
	installment_amount: string;
	installments_recovered_opening: string;
	installments_total: string;
	change_reason: string;
};

const emptyVersionForm = (): InstallmentVersionForm => ({
	effective_from: "",
	installment_amount: "",
	installments_recovered_opening: "0",
	installments_total: "",
	change_reason: "",
});

function NewInstallmentVersionDialog({
	open,
	onOpenChange,
	employeeId,
	advance,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	employeeId: string;
	advance: AdvanceResponse | null;
}) {
	const createVersion = useCreateAdvanceInstallmentVersion(employeeId);
	const [form, setForm] = useState<InstallmentVersionForm>(emptyVersionForm);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyVersionForm());
			setFormError(null);
		}
	}, [open]);

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		if (!advance) return;
		setFormError(null);

		if (!form.effective_from) {
			setFormError("Effective from is required.");
			return;
		}

		const validationError = validateInstallmentFields({
			principal: advance.principal,
			installmentAmount: form.installment_amount,
			recoveredOpening: form.installments_recovered_opening,
			total: form.installments_total,
		});
		if (validationError) {
			setFormError(validationError);
			return;
		}

		try {
			await createVersion.mutateAsync({
				advanceId: advance.id,
				body: {
					effective_from: form.effective_from,
					installment_amount: form.installment_amount.trim(),
					installments_recovered_opening: Number(form.installments_recovered_opening),
					installments_total: Number(form.installments_total),
					change_reason: form.change_reason.trim() || null,
				},
			});
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 422) {
				setFormError(error.detail || "Validation failed.");
				return;
			}
			setFormError(getErrorMessage(error, "Failed to create installment version."));
		}
	};

	const isSubmitting = createVersion.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.form}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>New Installment Version</DialogTitle>
					<DialogDescription>
						Schedule a new installment version for this advance.
					</DialogDescription>
				</DialogHeader>

				<form
					className="flex min-h-0 flex-1 flex-col"
					onSubmit={(event) => void handleSubmit(event)}
				>
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="niv-effective-from">Effective From</Label>
							<DatePicker
								id="niv-effective-from"
								value={form.effective_from ? parseApiDate(form.effective_from) : undefined}
								onValueChange={(date) =>
									setForm((prev) => ({
										...prev,
										effective_from: date ? toApiDate(date) : "",
									}))
								}
								disabled={isSubmitting}
								className="w-full"
								placeholder="Effective From"
								calendarProps={SCHEDULABLE_DATE_CALENDAR_PROPS}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="niv-amount">Installment Amount</Label>
							<Input
								id="niv-amount"
								inputMode="decimal"
								value={form.installment_amount}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, installment_amount: event.target.value }))
								}
								disabled={isSubmitting}
								placeholder="0.00"
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="niv-recovered">Installments Recovered (Opening)</Label>
							<Input
								id="niv-recovered"
								type="number"
								min={0}
								step={1}
								value={form.installments_recovered_opening}
								onChange={(event) =>
									setForm((prev) => ({
										...prev,
										installments_recovered_opening: event.target.value,
									}))
								}
								disabled={isSubmitting}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="niv-total">Installments Total</Label>
							<Input
								id="niv-total"
								type="number"
								min={1}
								step={1}
								value={form.installments_total}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, installments_total: event.target.value }))
								}
								disabled={isSubmitting}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="niv-change-reason">Change Reason (Optional)</Label>
							<Textarea
								id="niv-change-reason"
								value={form.change_reason}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, change_reason: event.target.value }))
								}
								disabled={isSubmitting}
								rows={2}
							/>
						</div>

						{formError ? (
							<p className="text-sm text-destructive" role="alert">
								{formError}
							</p>
						) : null}
					</DialogBody>

					<DialogFooter className="border-t px-6 py-4">
						<Button
							type="button"
							variant="outline"
							onClick={() => onOpenChange(false)}
							disabled={isSubmitting}
						>
							Cancel
						</Button>
						<Button type="submit" disabled={isSubmitting}>
							{isSubmitting ? "Saving…" : "Create Version"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
