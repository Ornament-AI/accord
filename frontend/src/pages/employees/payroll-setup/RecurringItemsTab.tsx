import { type FormEvent, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
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
	type RecurringInstructionResponse,
	useCreateRecurringInstruction,
	useCreateRecurringInstructionVersion,
	usePayComponentsList,
	useRecurringInstructions,
} from "@/lib/api/pay-setup";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { ApiError, getErrorMessage } from "@/lib/errors";
import { formatDate } from "@/lib/utils";

import { validateNonNegativeMoney, validatePositiveMoney } from "./money";

type RecurringItemsTabProps = {
	employeeId: string;
	asOf: string;
	canManage: boolean;
};

function formatEffectiveRange(
	from: string | null | undefined,
	to: string | null | undefined,
): string {
	const start = from ? formatDate(from) : "—";
	const end = to ? formatDate(to) : "present";
	return `${start} → ${end}`;
}

function formatAmountOrRate(row: RecurringInstructionResponse): string {
	if (row.amount != null && row.amount !== "") return row.amount;
	if (row.rate != null && row.rate !== "") return `${row.rate} (rate)`;
	return "—";
}

export function RecurringItemsTab({ employeeId, asOf, canManage }: RecurringItemsTabProps) {
	const instructionsQuery = useRecurringInstructions(employeeId, asOf);
	const componentsQuery = usePayComponentsList();
	const [addOpen, setAddOpen] = useState(false);
	const [versionTarget, setVersionTarget] = useState<RecurringInstructionResponse | null>(null);
	const [endTarget, setEndTarget] = useState<RecurringInstructionResponse | null>(null);

	const componentById = useMemo(() => {
		const map = new Map<string, { code: string; name: string }>();
		for (const component of componentsQuery.data ?? []) {
			map.set(component.id, { code: component.code, name: component.name });
		}
		return map;
	}, [componentsQuery.data]);

	const rows = instructionsQuery.data ?? [];

	return (
		<div className="grid gap-4" data-testid="recurring-items-tab">
			<div className="flex flex-wrap items-center justify-between gap-2">
				<h3 className="text-sm font-medium">Recurring items</h3>
				{canManage ? (
					<Button size="xs" onClick={() => setAddOpen(true)}>
						Add
					</Button>
				) : null}
			</div>

			{instructionsQuery.isLoading ? (
				<div className="grid gap-2">
					<Skeleton className="h-10 w-full" />
					<Skeleton className="h-10 w-full" />
				</div>
			) : null}

			{instructionsQuery.isError ? (
				<ErrorWithRetry
					message={getErrorMessage(instructionsQuery.error, "Failed to load recurring items.")}
					onRetry={() => void instructionsQuery.refetch()}
				/>
			) : null}

			{!instructionsQuery.isLoading && !instructionsQuery.isError ? (
				rows.length === 0 ? (
					<p className="text-sm text-muted-foreground">
						No recurring instructions as of this date.
					</p>
				) : (
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>Component</TableHead>
								<TableHead>Amount / rate</TableHead>
								<TableHead>Effective range</TableHead>
								{canManage ? <TableHead className="text-right">Actions</TableHead> : null}
							</TableRow>
						</TableHeader>
						<TableBody>
							{rows.map((row) => {
								const component = componentById.get(row.component_id);
								const label = component
									? `${component.code} — ${component.name}`
									: row.component_id;
								return (
									<TableRow key={row.id}>
										<TableCell>{label}</TableCell>
										<TableCell>{formatAmountOrRate(row)}</TableCell>
										<TableCell>
											{formatEffectiveRange(row.effective_from, row.effective_to)}
										</TableCell>
										{canManage ? (
											<TableCell className="text-right">
												<div className="flex justify-end gap-2">
													<Button size="xs" variant="outline" onClick={() => setVersionTarget(row)}>
														Add
													</Button>
													<Button size="xs" variant="outline" onClick={() => setEndTarget(row)}>
														End
													</Button>
												</div>
											</TableCell>
										) : null}
									</TableRow>
								);
							})}
						</TableBody>
					</Table>
				)
			) : null}

			{canManage ? (
				<>
					<AddInstructionDialog open={addOpen} onOpenChange={setAddOpen} employeeId={employeeId} />
					<NewVersionDialog
						open={Boolean(versionTarget)}
						onOpenChange={(open) => {
							if (!open) setVersionTarget(null);
						}}
						employeeId={employeeId}
						instruction={versionTarget}
					/>
					<EndInstructionDialog
						open={Boolean(endTarget)}
						onOpenChange={(open) => {
							if (!open) setEndTarget(null);
						}}
						employeeId={employeeId}
						instruction={endTarget}
					/>
				</>
			) : null}
		</div>
	);
}

type AddInstructionForm = {
	component_id: string;
	effective_from: string;
	amount: string;
	rate: string;
	reason: string;
};

const emptyAddForm = (): AddInstructionForm => ({
	component_id: "",
	effective_from: "",
	amount: "",
	rate: "",
	reason: "",
});

function AddInstructionDialog({
	open,
	onOpenChange,
	employeeId,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	employeeId: string;
}) {
	const createInstruction = useCreateRecurringInstruction(employeeId);
	const componentsQuery = usePayComponentsList();
	const [form, setForm] = useState<AddInstructionForm>(emptyAddForm);
	const [overlapError, setOverlapError] = useState<string | null>(null);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyAddForm());
			setOverlapError(null);
			setFormError(null);
		}
	}, [open]);

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setOverlapError(null);
		setFormError(null);

		if (!form.component_id) {
			setFormError("Component is required.");
			return;
		}
		if (!form.effective_from) {
			setFormError("Effective from is required.");
			return;
		}

		const hasAmount = form.amount.trim().length > 0;
		const hasRate = form.rate.trim().length > 0;
		if (hasAmount === hasRate) {
			setFormError("Provide exactly one of amount or rate.");
			return;
		}

		if (hasAmount) {
			const amountError = validatePositiveMoney(form.amount, "Amount");
			if (amountError) {
				setFormError(amountError);
				return;
			}
		}
		if (hasRate) {
			const rateError = validateNonNegativeMoney(form.rate, "Rate");
			if (rateError) {
				setFormError(rateError);
				return;
			}
		}

		try {
			await createInstruction.mutateAsync({
				component_id: form.component_id,
				effective_from: form.effective_from,
				amount: hasAmount ? form.amount.trim() : null,
				rate: hasRate ? form.rate.trim() : null,
				reason: form.reason.trim() || null,
			});
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				setOverlapError(error.detail || "Instruction periods overlap.");
				return;
			}
			setFormError(getErrorMessage(error, "Failed to create instruction."));
		}
	};

	const isSubmitting = createInstruction.isPending;
	const components = componentsQuery.data ?? [];

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.form}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>Add instruction</DialogTitle>
					<DialogDescription>
						Create a recurring payroll instruction for this employee.
					</DialogDescription>
				</DialogHeader>

				<form
					className="flex min-h-0 flex-1 flex-col"
					onSubmit={(event) => void handleSubmit(event)}
				>
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="add-ri-component">Component</Label>
							<Select
								value={form.component_id || null}
								onValueChange={(value) =>
									setForm((prev) => ({ ...prev, component_id: value ?? "" }))
								}
								disabled={isSubmitting}
							>
								<SelectTrigger id="add-ri-component" className="w-full">
									<SelectValue placeholder="Select component">
										{(value: string | null) => {
											const component = components.find((item) => item.id === value);
											return component
												? `${component.code} — ${component.name}`
												: "Select component";
										}}
									</SelectValue>
								</SelectTrigger>
								<SelectContent>
									{components.map((component) => (
										<SelectItem key={component.id} value={component.id}>
											{component.code} — {component.name}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-ri-effective-from">Effective from</Label>
							<Input
								id="add-ri-effective-from"
								type="date"
								value={form.effective_from}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, effective_from: event.target.value }))
								}
								disabled={isSubmitting}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-ri-amount">Amount</Label>
							<Input
								id="add-ri-amount"
								inputMode="decimal"
								value={form.amount}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, amount: event.target.value, rate: "" }))
								}
								disabled={isSubmitting || form.rate.trim().length > 0}
								placeholder="0.00"
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-ri-rate">Rate</Label>
							<Input
								id="add-ri-rate"
								inputMode="decimal"
								value={form.rate}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, rate: event.target.value, amount: "" }))
								}
								disabled={isSubmitting || form.amount.trim().length > 0}
								placeholder="0.00"
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-ri-reason">Reason (optional)</Label>
							<Textarea
								id="add-ri-reason"
								value={form.reason}
								onChange={(event) => setForm((prev) => ({ ...prev, reason: event.target.value }))}
								disabled={isSubmitting}
								rows={2}
							/>
						</div>

						{overlapError ? (
							<p className="text-sm text-destructive" role="alert" data-testid="ri-overlap-error">
								{overlapError}
							</p>
						) : null}

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
							{isSubmitting ? "Creating…" : "Add"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

type VersionForm = {
	effective_from: string;
	amount: string;
	rate: string;
	change_reason: string;
};

const emptyVersionForm = (): VersionForm => ({
	effective_from: "",
	amount: "",
	rate: "",
	change_reason: "",
});

function NewVersionDialog({
	open,
	onOpenChange,
	employeeId,
	instruction,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	employeeId: string;
	instruction: RecurringInstructionResponse | null;
}) {
	const createVersion = useCreateRecurringInstructionVersion(employeeId);
	const [form, setForm] = useState<VersionForm>(emptyVersionForm);
	const [overlapError, setOverlapError] = useState<string | null>(null);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyVersionForm());
			setOverlapError(null);
			setFormError(null);
		}
	}, [open]);

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		if (!instruction) return;
		setOverlapError(null);
		setFormError(null);

		if (!form.effective_from) {
			setFormError("Effective from is required.");
			return;
		}

		const hasAmount = form.amount.trim().length > 0;
		const hasRate = form.rate.trim().length > 0;
		if (hasAmount === hasRate) {
			setFormError("Provide exactly one of amount or rate.");
			return;
		}

		if (hasAmount) {
			const amountError = validatePositiveMoney(form.amount, "Amount");
			if (amountError) {
				setFormError(amountError);
				return;
			}
		}
		if (hasRate) {
			const rateError = validateNonNegativeMoney(form.rate, "Rate");
			if (rateError) {
				setFormError(rateError);
				return;
			}
		}

		try {
			await createVersion.mutateAsync({
				instructionId: instruction.id,
				body: {
					effective_from: form.effective_from,
					amount: hasAmount ? form.amount.trim() : null,
					rate: hasRate ? form.rate.trim() : null,
					change_reason: form.change_reason.trim() || null,
				},
			});
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				setOverlapError(error.detail || "Instruction periods overlap.");
				return;
			}
			setFormError(getErrorMessage(error, "Failed to create version."));
		}
	};

	const isSubmitting = createVersion.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.form}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>New version</DialogTitle>
					<DialogDescription>
						Create a new effective version for this recurring instruction.
					</DialogDescription>
				</DialogHeader>

				<form
					className="flex min-h-0 flex-1 flex-col"
					onSubmit={(event) => void handleSubmit(event)}
				>
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="nv-ri-effective-from">Effective from</Label>
							<Input
								id="nv-ri-effective-from"
								type="date"
								value={form.effective_from}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, effective_from: event.target.value }))
								}
								disabled={isSubmitting}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="nv-ri-amount">Amount</Label>
							<Input
								id="nv-ri-amount"
								inputMode="decimal"
								value={form.amount}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, amount: event.target.value, rate: "" }))
								}
								disabled={isSubmitting || form.rate.trim().length > 0}
								placeholder="0.00"
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="nv-ri-rate">Rate</Label>
							<Input
								id="nv-ri-rate"
								inputMode="decimal"
								value={form.rate}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, rate: event.target.value, amount: "" }))
								}
								disabled={isSubmitting || form.amount.trim().length > 0}
								placeholder="0.00"
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="nv-ri-change-reason">Change reason (optional)</Label>
							<Textarea
								id="nv-ri-change-reason"
								value={form.change_reason}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, change_reason: event.target.value }))
								}
								disabled={isSubmitting}
								rows={2}
							/>
						</div>

						{overlapError ? (
							<p className="text-sm text-destructive" role="alert">
								{overlapError}
							</p>
						) : null}

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
							{isSubmitting ? "Saving…" : "Create version"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

type EndForm = {
	end_on: string;
	change_reason: string;
};

const emptyEndForm = (): EndForm => ({
	end_on: "",
	change_reason: "",
});

function EndInstructionDialog({
	open,
	onOpenChange,
	employeeId,
	instruction,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	employeeId: string;
	instruction: RecurringInstructionResponse | null;
}) {
	const createVersion = useCreateRecurringInstructionVersion(employeeId);
	const [form, setForm] = useState<EndForm>(emptyEndForm);
	const [overlapError, setOverlapError] = useState<string | null>(null);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyEndForm());
			setOverlapError(null);
			setFormError(null);
		}
	}, [open]);

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		if (!instruction) return;
		setOverlapError(null);
		setFormError(null);

		if (!form.end_on) {
			setFormError("End on is required.");
			return;
		}

		try {
			await createVersion.mutateAsync({
				instructionId: instruction.id,
				body: {
					end_on: form.end_on,
					change_reason: form.change_reason.trim() || null,
				},
			});
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				setOverlapError(error.detail || "Instruction periods overlap.");
				return;
			}
			setFormError(getErrorMessage(error, "Failed to end instruction."));
		}
	};

	const isSubmitting = createVersion.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.compactForm}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>End instruction</DialogTitle>
					<DialogDescription>
						Terminate this recurring instruction on the selected date.
					</DialogDescription>
				</DialogHeader>

				<form
					className="flex min-h-0 flex-1 flex-col"
					onSubmit={(event) => void handleSubmit(event)}
					data-testid="end-instruction-form"
				>
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="end-ri-end-on">End on</Label>
							<Input
								id="end-ri-end-on"
								type="date"
								value={form.end_on}
								onChange={(event) => setForm((prev) => ({ ...prev, end_on: event.target.value }))}
								disabled={isSubmitting}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="end-ri-change-reason">Change reason (optional)</Label>
							<Textarea
								id="end-ri-change-reason"
								value={form.change_reason}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, change_reason: event.target.value }))
								}
								disabled={isSubmitting}
								rows={2}
							/>
						</div>

						{overlapError ? (
							<p className="text-sm text-destructive" role="alert">
								{overlapError}
							</p>
						) : null}

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
							{isSubmitting ? "Ending…" : "End instruction"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
