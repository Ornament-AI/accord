import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
	Dialog,
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
import { Skeleton } from "@/components/ui/skeleton";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
	ADVANCE_TYPES,
	type AdvanceResponse,
	type AdvanceType,
	advanceTypeLabel,
	useAdvances,
	useCreateAdvance,
	useCreateAdvanceInstallmentVersion,
} from "@/lib/api/pay-setup";
import { ApiError, getErrorMessage } from "@/lib/errors";
import { formatDate } from "@/lib/utils";

import { parseMoneyString, validatePositiveMoney } from "./money";

type AdvancesTabProps = {
	employeeId: string;
	asOf: string;
	canManage: boolean;
};

function formatProgress(row: AdvanceResponse): string {
	const recovered = row.installments_recovered_opening;
	const total = row.installments_total;
	if (recovered == null || total == null) return "—";
	return `${recovered}/${total}`;
}

export function AdvancesTab({ employeeId, asOf, canManage }: AdvancesTabProps) {
	const advancesQuery = useAdvances(employeeId, asOf);
	const [addOpen, setAddOpen] = useState(false);
	const [versionTarget, setVersionTarget] = useState<AdvanceResponse | null>(null);

	const rows = advancesQuery.data ?? [];

	return (
		<div className="grid gap-4" data-testid="advances-tab">
			<div className="flex flex-wrap items-center justify-between gap-2">
				<h3 className="text-sm font-medium">Advances</h3>
				{canManage ? (
					<Button size="sm" onClick={() => setAddOpen(true)}>
						Add advance
					</Button>
				) : null}
			</div>

			{advancesQuery.isLoading ? (
				<div className="grid gap-2">
					<Skeleton className="h-10 w-full" />
					<Skeleton className="h-10 w-full" />
				</div>
			) : null}

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
								<TableHead>Principal</TableHead>
								<TableHead>Sanctioned on</TableHead>
								<TableHead>Installment</TableHead>
								<TableHead>Progress</TableHead>
								{canManage ? <TableHead className="text-right">Actions</TableHead> : null}
							</TableRow>
						</TableHeader>
						<TableBody>
							{rows.map((row) => (
								<TableRow key={row.id}>
									<TableCell>{advanceTypeLabel(row.advance_type)}</TableCell>
									<TableCell>{row.principal}</TableCell>
									<TableCell>{formatDate(row.sanctioned_on)}</TableCell>
									<TableCell>{row.installment_amount ?? "—"}</TableCell>
									<TableCell>{formatProgress(row)}</TableCell>
									{canManage ? (
										<TableCell className="text-right">
											<Button size="sm" variant="outline" onClick={() => setVersionTarget(row)}>
												New installment version
											</Button>
										</TableCell>
									) : null}
								</TableRow>
							))}
						</TableBody>
					</Table>
				)
			) : null}

			{canManage ? (
				<>
					<AddAdvanceDialog open={addOpen} onOpenChange={setAddOpen} employeeId={employeeId} />
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

	const installmentError = validatePositiveMoney(args.installmentAmount, "Installment amount");
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
		return "Installments total must be a positive integer.";
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
			<DialogContent className="sm:max-w-lg">
				<DialogHeader>
					<DialogTitle>Add advance</DialogTitle>
					<DialogDescription>
						Record an advance and its first installment schedule for this employee.
					</DialogDescription>
				</DialogHeader>

				<form
					className="grid gap-4"
					onSubmit={(event) => void handleSubmit(event)}
					data-testid="add-advance-form"
				>
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
								<SelectValue />
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
							onChange={(event) => setForm((prev) => ({ ...prev, principal: event.target.value }))}
							disabled={isSubmitting}
							placeholder="0.00"
						/>
					</div>

					<div className="grid gap-2">
						<Label htmlFor="add-adv-sanctioned-on">Sanctioned on</Label>
						<Input
							id="add-adv-sanctioned-on"
							type="date"
							value={form.sanctioned_on}
							onChange={(event) =>
								setForm((prev) => ({ ...prev, sanctioned_on: event.target.value }))
							}
							disabled={isSubmitting}
						/>
					</div>

					<div className="grid gap-2">
						<Label htmlFor="add-adv-reference">Reference (optional)</Label>
						<Input
							id="add-adv-reference"
							value={form.reference}
							onChange={(event) => setForm((prev) => ({ ...prev, reference: event.target.value }))}
							disabled={isSubmitting}
						/>
					</div>

					<fieldset className="grid gap-3 rounded-md border p-3">
						<legend className="px-1 text-sm font-medium">First installment</legend>

						<div className="grid gap-2">
							<Label htmlFor="add-adv-inst-from">Effective from</Label>
							<Input
								id="add-adv-inst-from"
								type="date"
								value={form.effective_from}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, effective_from: event.target.value }))
								}
								disabled={isSubmitting}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-adv-inst-amount">Installment amount</Label>
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
							<Label htmlFor="add-adv-inst-recovered">Installments recovered (opening)</Label>
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
							<Label htmlFor="add-adv-inst-total">Installments total</Label>
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

					<DialogFooter>
						<Button
							type="button"
							variant="outline"
							onClick={() => onOpenChange(false)}
							disabled={isSubmitting}
						>
							Cancel
						</Button>
						<Button type="submit" disabled={isSubmitting}>
							{isSubmitting ? "Creating…" : "Add advance"}
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
			<DialogContent className="sm:max-w-lg">
				<DialogHeader>
					<DialogTitle>New installment version</DialogTitle>
					<DialogDescription>
						Schedule a new installment version for this advance.
					</DialogDescription>
				</DialogHeader>

				<form className="grid gap-4" onSubmit={(event) => void handleSubmit(event)}>
					<div className="grid gap-2">
						<Label htmlFor="niv-effective-from">Effective from</Label>
						<Input
							id="niv-effective-from"
							type="date"
							value={form.effective_from}
							onChange={(event) =>
								setForm((prev) => ({ ...prev, effective_from: event.target.value }))
							}
							disabled={isSubmitting}
						/>
					</div>

					<div className="grid gap-2">
						<Label htmlFor="niv-amount">Installment amount</Label>
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
						<Label htmlFor="niv-recovered">Installments recovered (opening)</Label>
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
						<Label htmlFor="niv-total">Installments total</Label>
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
						<Label htmlFor="niv-change-reason">Change reason (optional)</Label>
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

					<DialogFooter>
						<Button
							type="button"
							variant="outline"
							onClick={() => onOpenChange(false)}
							disabled={isSubmitting}
						>
							Cancel
						</Button>
						<Button type="submit" disabled={isSubmitting}>
							{isSubmitting ? "Saving…" : "Create version"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
