import { type FormEvent, useEffect, useMemo, useState } from "react";

import { isInteractiveRowTarget } from "@/components/table-interactions";
import { Button } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
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
import { parseApiDate, toApiDate } from "@/lib/api/employees";
import {
	type RecurringInstructionResponse,
	useCreateRecurringInstruction,
	useCreateRecurringInstructionVersion,
	usePayComponentsList,
	useRecurringInstructions,
} from "@/lib/api/pay-setup";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { payComponentEntityLabel } from "@/lib/entity-labels";
import { ApiError, getErrorMessage } from "@/lib/errors";

import { validateNonNegativeMoney, validatePositiveMoney } from "./money";

type RecurringItemsTabProps = {
	employeeId: string;
	asOf: string;
	canManage: boolean;
	createOpen: boolean;
	onCreateOpenChange: (open: boolean) => void;
};

function formatAmountOrRate(row: RecurringInstructionResponse): string {
	if (row.amount != null && row.amount !== "") return row.amount;
	if (row.rate != null && row.rate !== "") return `${row.rate} (rate)`;
	return "—";
}

export function RecurringItemsTab({
	employeeId,
	asOf,
	canManage,
	createOpen,
	onCreateOpenChange,
}: RecurringItemsTabProps) {
	const instructionsQuery = useRecurringInstructions(employeeId, asOf);
	const componentsQuery = usePayComponentsList();
	const [versionTarget, setVersionTarget] = useState<RecurringInstructionResponse | null>(null);
	const [endTarget, setEndTarget] = useState<RecurringInstructionResponse | null>(null);

	const componentLabelById = useMemo(() => {
		const map = new Map<string, string>();
		for (const component of componentsQuery.data ?? []) {
			map.set(component.id, payComponentEntityLabel(component));
		}
		return map;
	}, [componentsQuery.data]);

	const rows = instructionsQuery.data ?? [];

	return (
		<div className="grid gap-4" data-testid="recurring-items-tab">
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
								<TableHead className="text-right">Amount / Rate</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{rows.map((row) => {
								const label = componentLabelById.get(row.component_id) ?? row.component_id;
								return (
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
													New Version
												</button>
											) : null}
											{label}
										</TableCell>
										<TableCell className="text-right">{formatAmountOrRate(row)}</TableCell>
									</TableRow>
								);
							})}
						</TableBody>
					</Table>
				)
			) : null}

			{canManage ? (
				<>
					<AddInstructionDialog
						open={createOpen}
						onOpenChange={onCreateOpenChange}
						employeeId={employeeId}
					/>
					<NewVersionDialog
						open={Boolean(versionTarget)}
						onOpenChange={(open) => {
							if (!open) setVersionTarget(null);
						}}
						onRequestEnd={() => {
							setEndTarget(versionTarget);
							setVersionTarget(null);
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
					<DialogTitle>Add Instruction</DialogTitle>
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
												? payComponentEntityLabel(component, "Select component")
												: "Select component";
										}}
									</SelectValue>
								</SelectTrigger>
								<SelectContent>
									{components.map((component) => (
										<SelectItem key={component.id} value={component.id}>
											{payComponentEntityLabel(component)}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-ri-effective-from">Effective From</Label>
							<DatePicker
								id="add-ri-effective-from"
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
							<Label htmlFor="add-ri-reason">Reason (Optional)</Label>
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
};

const emptyVersionForm = (): VersionForm => ({
	effective_from: "",
	amount: "",
	rate: "",
});

function NewVersionDialog({
	open,
	onOpenChange,
	onRequestEnd,
	employeeId,
	instruction,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onRequestEnd: () => void;
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
					change_reason: null,
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
					<DialogTitle>New Version</DialogTitle>
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
							<Label htmlFor="nv-ri-effective-from">Effective From</Label>
							<DatePicker
								id="nv-ri-effective-from"
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

					<DialogFooter className="border-t px-6 py-4 sm:justify-between">
						<Button
							type="button"
							variant="outline"
							onClick={() => {
								onOpenChange(false);
								onRequestEnd();
							}}
							disabled={isSubmitting}
						>
							End
						</Button>
						<div className="flex flex-wrap gap-2">
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
						</div>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

type EndForm = {
	end_on: string;
};

const emptyEndForm = (): EndForm => ({
	end_on: "",
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
					change_reason: null,
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
					<DialogTitle>End Instruction</DialogTitle>
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
							<Label htmlFor="end-ri-end-on">End On</Label>
							<DatePicker
								id="end-ri-end-on"
								value={form.end_on ? parseApiDate(form.end_on) : undefined}
								onValueChange={(date) =>
									setForm((prev) => ({ ...prev, end_on: date ? toApiDate(date) : "" }))
								}
								disabled={isSubmitting}
								className="w-full"
								placeholder="End On"
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
							{isSubmitting ? "Ending…" : "End Instruction"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
