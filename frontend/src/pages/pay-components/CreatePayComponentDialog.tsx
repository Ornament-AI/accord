import { type FormEvent, useEffect, useState } from "react";

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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
	CLASSIFICATIONS,
	type Classification,
	classificationLabel,
	REGISTER_COLUMNS_BY_CLASSIFICATION,
	type RegisterColumn,
	registerColumnLabel,
	type ScheduleKind,
	useCreatePayComponent,
	usePayComponentsList,
} from "@/lib/api/pay-setup";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { ApiError } from "@/lib/errors";

type CreatePayComponentDialogProps = {
	open: boolean;
	onOpenChange: (open: boolean) => void;
};

type FormState = {
	code: string;
	name: string;
	classification: Classification;
	register_column: RegisterColumn | "";
	display_order: string;
	employer_transfer: boolean;
	transfer_of: string;
	schedule_kind: ScheduleKind | "";
	schedule_title: string;
	schedule_account_head: string;
};

const emptyForm = (): FormState => ({
	code: "",
	name: "",
	classification: "earning",
	register_column: "",
	display_order: "0",
	employer_transfer: false,
	transfer_of: "",
	schedule_kind: "",
	schedule_title: "",
	schedule_account_head: "",
});

const OFF_BILL_VALUE = "__offbill__";

export function CreatePayComponentDialog({ open, onOpenChange }: CreatePayComponentDialogProps) {
	const createComponent = useCreatePayComponent();
	const componentsQuery = usePayComponentsList();
	const [form, setForm] = useState<FormState>(emptyForm);
	const [codeError, setCodeError] = useState<string | null>(null);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyForm());
			setCodeError(null);
			setFormError(null);
		}
	}, [open]);

	const setField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setCodeError(null);
		setFormError(null);

		if (!form.code.trim()) {
			setCodeError("Code is required");
			return;
		}
		if (!form.name.trim()) {
			setFormError("Name is required.");
			return;
		}

		const displayOrder = Number(form.display_order);
		if (!Number.isFinite(displayOrder)) {
			setFormError("Display order must be a number.");
			return;
		}

		try {
			await createComponent.mutateAsync({
				code: form.code.trim(),
				name: form.name.trim(),
				classification: form.classification,
				register_column: form.register_column || null,
				display_order: displayOrder,
				employer_transfer: form.employer_transfer,
				transfer_of: form.employer_transfer ? form.transfer_of || null : null,
				schedule_kind: form.schedule_kind || null,
				schedule_title: form.schedule_kind ? form.schedule_title.trim() || null : null,
				schedule_account_head: form.schedule_kind
					? form.schedule_account_head.trim() || null
					: null,
			});
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				setCodeError(error.detail || "A component with this code already exists");
				return;
			}
			setFormError(error instanceof Error ? error.message : "Failed to create pay component.");
		}
	};

	const isSubmitting = createComponent.isPending;
	const employerContributions = (componentsQuery.data ?? []).filter(
		(component) => component.classification === "employer_contribution" && component.is_active,
	);
	const registerColumns = REGISTER_COLUMNS_BY_CLASSIFICATION[
		form.classification
	] as readonly RegisterColumn[];

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.compactForm}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>New Pay Component</DialogTitle>
					<DialogDescription>
						Create a pay component. Code and classification cannot be changed later.
					</DialogDescription>
				</DialogHeader>

				<form
					className="flex min-h-0 flex-1 flex-col"
					onSubmit={(event) => void handleSubmit(event)}
				>
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="create-pc-code">Code</Label>
							<Input
								id="create-pc-code"
								value={form.code}
								onChange={(event) => {
									setField("code", event.target.value);
									setCodeError(null);
								}}
								aria-invalid={codeError ? true : undefined}
								disabled={isSubmitting}
								autoComplete="off"
							/>
							{codeError ? (
								<p className="text-sm text-destructive" role="alert">
									{codeError}
								</p>
							) : null}
						</div>

						<div className="grid gap-2">
							<Label htmlFor="create-pc-name">Name</Label>
							<Input
								id="create-pc-name"
								value={form.name}
								onChange={(event) => setField("name", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="create-pc-classification">Classification</Label>
							<Select
								value={form.classification}
								onValueChange={(value) => {
									const classification = value as Classification;
									setForm((prev) => ({
										...prev,
										classification,
										employer_transfer: [
											"ag_deduction",
											"treasury_deduction",
											"external_recovery",
										].includes(classification)
											? prev.employer_transfer
											: false,
										transfer_of: [
											"ag_deduction",
											"treasury_deduction",
											"external_recovery",
										].includes(classification)
											? prev.transfer_of
											: "",
										register_column: REGISTER_COLUMNS_BY_CLASSIFICATION[classification].includes(
											prev.register_column as never,
										)
											? prev.register_column
											: "",
									}));
								}}
								disabled={isSubmitting}
							>
								<SelectTrigger id="create-pc-classification" className="w-full">
									<SelectValue>
										{(value: Classification | null) =>
											value ? classificationLabel(value) : "Select classification"
										}
									</SelectValue>
								</SelectTrigger>
								<SelectContent>
									{CLASSIFICATIONS.map((classification) => (
										<SelectItem key={classification} value={classification}>
											{classificationLabel(classification)}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="create-pc-register-column">Pay Bill Column</Label>
							<Select
								value={form.register_column || "none"}
								onValueChange={(value) =>
									setField("register_column", value === "none" ? "" : (value as RegisterColumn))
								}
								disabled={isSubmitting || registerColumns.length === 0}
							>
								<SelectTrigger id="create-pc-register-column" className="w-full">
									<SelectValue placeholder="Not shown in Pay Bill" />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="none">Not shown in Pay Bill</SelectItem>
									{registerColumns.map((column) => (
										<SelectItem key={column} value={column}>
											{registerColumnLabel(column)}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
							<p className="text-xs text-muted-foreground">
								Maps this component to its canonical Pay Bill column.
							</p>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="create-pc-display-order">Display Order</Label>
							<Input
								id="create-pc-display-order"
								type="number"
								value={form.display_order}
								onChange={(event) => setField("display_order", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="create-pc-schedule-kind">Export Schedule</Label>
							<Select
								value={form.schedule_kind || "none"}
								onValueChange={(value) =>
									setField("schedule_kind", value === "none" ? "" : (value as ScheduleKind))
								}
								disabled={isSubmitting}
							>
								<SelectTrigger id="create-pc-schedule-kind" className="w-full">
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="none">No separate schedule</SelectItem>
									<SelectItem value="simple_component">Component schedule</SelectItem>
									<SelectItem value="loan_installment">Loan installment schedule</SelectItem>
								</SelectContent>
							</Select>
						</div>

						{form.schedule_kind ? (
							<>
								<div className="grid gap-2">
									<Label htmlFor="create-pc-schedule-title">Schedule Title</Label>
									<Input
										id="create-pc-schedule-title"
										value={form.schedule_title}
										onChange={(event) => setField("schedule_title", event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="create-pc-schedule-account-head">Account Head</Label>
									<Input
										id="create-pc-schedule-account-head"
										value={form.schedule_account_head}
										onChange={(event) => setField("schedule_account_head", event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
							</>
						) : null}

						{["ag_deduction", "treasury_deduction", "external_recovery"].includes(
							form.classification,
						) ? (
							<>
								<div className="flex items-center justify-between gap-4">
									<div className="grid gap-1">
										<Label htmlFor="create-pc-employer-transfer">Employer Transfer</Label>
										<p className="text-xs text-muted-foreground">
											Marks an employer-funded deduction.
										</p>
									</div>
									<Switch
										id="create-pc-employer-transfer"
										checked={form.employer_transfer}
										onCheckedChange={(checked) =>
											setForm((prev) => ({
												...prev,
												employer_transfer: checked,
												transfer_of: checked ? prev.transfer_of : "",
											}))
										}
										disabled={isSubmitting}
									/>
								</div>

								{form.employer_transfer ? (
									<div className="grid gap-2">
										<Label htmlFor="create-pc-transfer-of">Paired Employer Contribution</Label>
										<Select
											value={form.transfer_of || OFF_BILL_VALUE}
											onValueChange={(value) =>
												setField("transfer_of", value === OFF_BILL_VALUE ? "" : value)
											}
											disabled={isSubmitting}
										>
											<SelectTrigger id="create-pc-transfer-of" className="w-full">
												<SelectValue />
											</SelectTrigger>
											<SelectContent>
												<SelectItem value={OFF_BILL_VALUE}>None (off-bill)</SelectItem>
												{employerContributions.map((component) => (
													<SelectItem key={component.id} value={component.code}>
														{component.name} ({component.code})
													</SelectItem>
												))}
											</SelectContent>
										</Select>
										<p className="text-xs text-muted-foreground">
											Leave unpaired when the employer share is off-bill.
										</p>
									</div>
								) : null}
							</>
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
							{isSubmitting ? "Creating…" : "Create Component"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
