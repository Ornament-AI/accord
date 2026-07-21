import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
	CALC_KINDS,
	type CalcKind,
	type ComponentRateVersionCreate,
	calcKindLabel,
	calcKindUsesAmount,
	calcKindUsesBasis,
	calcKindUsesRate,
	type PayComponentResponse,
	ROUNDING_RULES,
	type RoundingRule,
	roundingRuleLabel,
	useCreateComponentRateVersion,
} from "@/lib/api/pay-setup";
import { parseApiDate, toApiDate } from "@/lib/calendar-date";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { payComponentEntityLabel } from "@/lib/entity-labels";
import { ApiError } from "@/lib/errors";

type CreateRateVersionDialogProps = {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	componentId: string;
	/** Other components available as basis codes (typically exclude the current one). */
	basisOptions: PayComponentResponse[];
};

type FormState = {
	effective_from: string;
	calc_kind: CalcKind;
	rounding_rule: RoundingRule;
	amount: string;
	rate: string;
	basis: string[];
	change_reason: string;
};

const emptyForm = (): FormState => ({
	effective_from: "",
	calc_kind: "fixed_recurring_amount",
	rounding_rule: "ROUND_HALF_UP_RUPEE",
	amount: "",
	rate: "",
	basis: [],
	change_reason: "",
});

export function CreateRateVersionDialog({
	open,
	onOpenChange,
	componentId,
	basisOptions,
}: CreateRateVersionDialogProps) {
	const createVersion = useCreateComponentRateVersion(componentId);
	const [form, setForm] = useState<FormState>(emptyForm);
	const [overlapError, setOverlapError] = useState<string | null>(null);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyForm());
			setOverlapError(null);
			setFormError(null);
		}
	}, [open]);

	const showAmount = calcKindUsesAmount(form.calc_kind);
	const showRate = calcKindUsesRate(form.calc_kind);
	const showBasis = calcKindUsesBasis(form.calc_kind);

	const toggleBasis = (code: string, checked: boolean) => {
		setForm((prev) => ({
			...prev,
			basis: checked
				? prev.basis.includes(code)
					? prev.basis
					: [...prev.basis, code]
				: prev.basis.filter((item) => item !== code),
		}));
	};

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setOverlapError(null);
		setFormError(null);

		if (!form.effective_from) {
			setFormError("Effective from is required.");
			return;
		}

		const body: ComponentRateVersionCreate = {
			effective_from: form.effective_from,
			calc_kind: form.calc_kind,
			rounding_rule: form.rounding_rule,
			change_reason: form.change_reason.trim() || null,
		};

		if (showAmount) {
			if (!form.amount.trim()) {
				setFormError("Amount is required for this calculation kind.");
				return;
			}
			body.amount = form.amount.trim();
		}

		if (showRate) {
			if (!form.rate.trim()) {
				setFormError("Rate is required for this calculation kind.");
				return;
			}
			body.rate = form.rate.trim();
		}

		if (showBasis) {
			if (form.calc_kind === "percentage_of_component_bases" && form.basis.length === 0) {
				setFormError("Select at least one basis component.");
				return;
			}
			if (form.basis.length > 0) {
				body.basis = form.basis;
			}
		}

		try {
			await createVersion.mutateAsync(body);
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				setOverlapError(error.detail || "Rate version periods overlap.");
				return;
			}
			setFormError(error instanceof Error ? error.message : "Failed to create rate version.");
		}
	};

	const isSubmitting = createVersion.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.form}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>New Rate Version</DialogTitle>
					<DialogDescription>
						Add an effective rate version for this pay component.
					</DialogDescription>
				</DialogHeader>

				<form
					className="flex min-h-0 flex-1 flex-col"
					onSubmit={(event) => void handleSubmit(event)}
				>
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="create-rv-effective-from">Effective From</Label>
							<DatePicker
								id="create-rv-effective-from"
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
							<Label htmlFor="create-rv-calc-kind">Calculation Kind</Label>
							<Select
								value={form.calc_kind}
								onValueChange={(value) =>
									setForm((prev) => ({
										...prev,
										calc_kind: value as CalcKind,
										amount: "",
										rate: "",
										basis: [],
									}))
								}
								disabled={isSubmitting}
							>
								<SelectTrigger id="create-rv-calc-kind" className="w-full">
									<SelectValue>
										{(value: CalcKind | null) =>
											value ? calcKindLabel(value) : "Select calculation kind"
										}
									</SelectValue>
								</SelectTrigger>
								<SelectContent>
									{CALC_KINDS.map((kind) => (
										<SelectItem key={kind} value={kind}>
											{calcKindLabel(kind)}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>

						{showAmount ? (
							<div className="grid gap-2">
								<Label htmlFor="create-rv-amount">Amount</Label>
								<Input
									id="create-rv-amount"
									inputMode="decimal"
									value={form.amount}
									onChange={(event) => setForm((prev) => ({ ...prev, amount: event.target.value }))}
									disabled={isSubmitting}
									placeholder="0.00"
								/>
							</div>
						) : null}

						{showRate ? (
							<div className="grid gap-2">
								<Label htmlFor="create-rv-rate">Rate</Label>
								<Input
									id="create-rv-rate"
									inputMode="decimal"
									value={form.rate}
									onChange={(event) => setForm((prev) => ({ ...prev, rate: event.target.value }))}
									disabled={isSubmitting}
									placeholder="0.0000"
								/>
							</div>
						) : null}

						{showBasis ? (
							<fieldset className="grid gap-2">
								<legend className="text-sm font-medium">Basis Components</legend>
								<div className="grid max-h-40 gap-2 overflow-y-auto rounded-md border p-3">
									{basisOptions.length === 0 ? (
										<p className="text-sm text-muted-foreground">
											No other components available for basis.
										</p>
									) : (
										basisOptions.map((option) => {
											const checkboxId = `create-rv-basis-${option.code}`;
											return (
												<div key={option.id} className="flex items-center gap-2">
													<Checkbox
														id={checkboxId}
														checked={form.basis.includes(option.code)}
														onCheckedChange={(checked) =>
															toggleBasis(option.code, checked === true)
														}
														disabled={isSubmitting}
													/>
													<Label htmlFor={checkboxId} className="font-normal">
														{payComponentEntityLabel(option)}
													</Label>
												</div>
											);
										})
									)}
								</div>
							</fieldset>
						) : null}

						<div className="grid gap-2">
							<Label htmlFor="create-rv-rounding">Rounding Rule</Label>
							<Select
								value={form.rounding_rule}
								onValueChange={(value) =>
									setForm((prev) => ({
										...prev,
										rounding_rule: value as RoundingRule,
									}))
								}
								disabled={isSubmitting}
							>
								<SelectTrigger id="create-rv-rounding" className="w-full">
									<SelectValue>
										{(value: RoundingRule | null) =>
											value ? roundingRuleLabel(value) : "Select rounding rule"
										}
									</SelectValue>
								</SelectTrigger>
								<SelectContent>
									{ROUNDING_RULES.map((rule) => (
										<SelectItem key={rule} value={rule}>
											{roundingRuleLabel(rule)}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="create-rv-change-reason">Change Reason (Optional)</Label>
							<Textarea
								id="create-rv-change-reason"
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
							{isSubmitting ? "Creating…" : "Create Rate Version"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
