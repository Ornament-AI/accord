import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { DatePicker, HISTORICAL_DATE_CALENDAR_PROPS } from "@/components/ui/date-picker";
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
import { useEmployeesList } from "@/lib/api/employees";
import { usePayComponentsList } from "@/lib/api/pay-setup";
import {
	INPUT_KINDS,
	type InputKind,
	type PayrollRunInputResponse,
	useUpsertPayrollRunInput,
} from "@/lib/api/payroll-runs";
import { parseApiDate, toApiDate } from "@/lib/calendar-date";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { employeeEntityLabel, payComponentEntityLabel } from "@/lib/entity-labels";
import { inputKindLabel } from "@/lib/payroll-display";

type UpsertInputDialogProps = {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	runId: string;
	editing?: PayrollRunInputResponse | null;
};

type FormState = {
	employee_id: string;
	component_code: string;
	input_kind: InputKind;
	amount: string;
	rate: string;
	service_period_start: string;
	service_period_end: string;
	reason: string;
	employee_search: string;
};

const emptyForm = (): FormState => ({
	employee_id: "",
	component_code: "",
	input_kind: "exception",
	amount: "",
	rate: "",
	service_period_start: "",
	service_period_end: "",
	reason: "",
	employee_search: "",
});

function formFromInput(input: PayrollRunInputResponse): FormState {
	const inputKind = (
		INPUT_KINDS.includes(input.input_kind as InputKind) ? input.input_kind : "exception"
	) as InputKind;
	return {
		employee_id: input.employee_id,
		component_code: input.component_code,
		input_kind: inputKind,
		amount: input.amount ?? "",
		rate: inputKind === "override" ? (input.rate ?? "") : "",
		service_period_start: input.service_period_start ?? "",
		service_period_end: input.service_period_end ?? "",
		reason: input.reason,
		employee_search: "",
	};
}

export function UpsertInputDialog({
	open,
	onOpenChange,
	runId,
	editing = null,
}: UpsertInputDialogProps) {
	const upsertInput = useUpsertPayrollRunInput(runId);
	const componentsQuery = usePayComponentsList();
	const [form, setForm] = useState<FormState>(emptyForm);
	const [formError, setFormError] = useState<string | null>(null);

	const employeesQuery = useEmployeesList({
		search: form.employee_search.trim() || null,
		page: 1,
		size: 20,
	});
	const employees = employeesQuery.data?.items ?? [];
	const components = (componentsQuery.data ?? []).filter((component) => component.is_active);

	const isEdit = Boolean(editing);

	useEffect(() => {
		if (!open) {
			setForm(emptyForm());
			setFormError(null);
			return;
		}
		setForm(editing ? formFromInput(editing) : emptyForm());
		setFormError(null);
	}, [open, editing]);

	const setField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setFormError(null);

		if (!form.employee_id) {
			setFormError("Select an employee.");
			return;
		}
		if (!form.component_code.trim()) {
			setFormError("Component code is required.");
			return;
		}
		if (!form.reason.trim()) {
			setFormError("Reason is required.");
			return;
		}
		const hasAmount = Boolean(form.amount.trim());
		const hasRate = Boolean(form.rate.trim());
		if (hasAmount === hasRate) {
			setFormError("Provide exactly one of amount or rate.");
			return;
		}
		if (hasRate && form.input_kind !== "override") {
			setFormError("Rate is available only for overrides.");
			return;
		}
		const hasServiceStart = Boolean(form.service_period_start);
		const hasServiceEnd = Boolean(form.service_period_end);
		if (hasServiceStart !== hasServiceEnd) {
			setFormError("Enter both service period dates, or leave both blank.");
			return;
		}
		if (
			form.service_period_start &&
			form.service_period_end &&
			form.service_period_start > form.service_period_end
		) {
			setFormError("Service period start must be on or before service period end.");
			return;
		}

		try {
			await upsertInput.mutateAsync({
				employeeId: form.employee_id,
				componentCode: form.component_code.trim(),
				body: {
					input_kind: form.input_kind,
					amount: hasAmount ? form.amount.trim() : null,
					rate: hasRate ? form.rate.trim() : null,
					reason: form.reason.trim(),
					service_period_start: form.service_period_start || null,
					service_period_end: form.service_period_end || null,
					expected_version: editing?.version ?? null,
				},
			});
			onOpenChange(false);
		} catch (error) {
			setFormError(error instanceof Error ? error.message : "Failed to save input.");
		}
	};

	const isSubmitting = upsertInput.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.compactForm}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>{isEdit ? "Edit Run Input" : "Add Run Input"}</DialogTitle>
					<DialogDescription>
						{isEdit
							? "Update this draft input. Reason is required."
							: "Add an exception, override, or one-time input for a draft run."}
					</DialogDescription>
				</DialogHeader>

				<form
					className="flex min-h-0 flex-1 flex-col"
					onSubmit={(event) => void handleSubmit(event)}
				>
					<DialogBody className="grid gap-4 pb-8">
						{!isEdit ? (
							<>
								<div className="grid gap-2">
									<Label htmlFor="upsert-input-employee-search">Search Employees</Label>
									<Input
										id="upsert-input-employee-search"
										value={form.employee_search}
										onChange={(event) => setField("employee_search", event.target.value)}
										disabled={isSubmitting}
										placeholder="Name, number, or Sevarth ID"
										autoComplete="off"
									/>
								</div>

								<div className="grid gap-2">
									<Label htmlFor="upsert-input-employee">Employee</Label>
									<Select
										value={form.employee_id || null}
										onValueChange={(value) => setField("employee_id", value ?? "")}
										disabled={isSubmitting || employeesQuery.isLoading}
									>
										<SelectTrigger id="upsert-input-employee" className="w-full">
											<SelectValue placeholder="Select employee">
												{(value: string | null) => {
													const employee = employees.find((item) => item.id === value);
													return employee
														? employeeEntityLabel(employee, "Select employee")
														: "Select employee";
												}}
											</SelectValue>
										</SelectTrigger>
										<SelectContent>
											{employees.map((employee) => (
												<SelectItem key={employee.id} value={employee.id}>
													{employeeEntityLabel(employee)}
												</SelectItem>
											))}
										</SelectContent>
									</Select>
								</div>

								<div className="grid gap-2">
									<Label htmlFor="upsert-input-component">Component</Label>
									<Select
										value={form.component_code || null}
										onValueChange={(value) => setField("component_code", value ?? "")}
										disabled={isSubmitting || componentsQuery.isLoading}
									>
										<SelectTrigger id="upsert-input-component" className="w-full">
											<SelectValue placeholder="Select component">
												{(value: string | null) => {
													const component = components.find((item) => item.code === value);
													return component
														? payComponentEntityLabel(component)
														: "Select component";
												}}
											</SelectValue>
										</SelectTrigger>
										<SelectContent>
											{components.map((component) => (
												<SelectItem key={component.id} value={component.code}>
													{payComponentEntityLabel(component)}
												</SelectItem>
											))}
										</SelectContent>
									</Select>
								</div>
							</>
						) : (
							<div className="grid gap-1 text-sm">
								<p>
									<span className="text-muted-foreground">Employee:</span> {editing?.employee_id}
								</p>
								<p>
									<span className="text-muted-foreground">Component:</span>{" "}
									{editing?.component_code}
								</p>
							</div>
						)}

						<div className="grid gap-2">
							<Label htmlFor="upsert-input-kind">Input Kind</Label>
							<Select
								value={form.input_kind}
								onValueChange={(value) => {
									const inputKind = value as InputKind;
									setForm((previous) => ({
										...previous,
										input_kind: inputKind,
										rate: inputKind === "override" ? previous.rate : "",
									}));
								}}
								disabled={isSubmitting}
							>
								<SelectTrigger id="upsert-input-kind" className="w-full">
									<SelectValue>
										{(value: InputKind | null) =>
											value ? inputKindLabel(value) : "Select input kind"
										}
									</SelectValue>
								</SelectTrigger>
								<SelectContent>
									{INPUT_KINDS.map((kind) => (
										<SelectItem key={kind} value={kind}>
											{inputKindLabel(kind)}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="upsert-input-amount">Amount</Label>
							<Input
								id="upsert-input-amount"
								value={form.amount}
								onChange={(event) => {
									setField("amount", event.target.value);
									if (event.target.value) setField("rate", "");
								}}
								disabled={isSubmitting || Boolean(form.rate.trim())}
								inputMode="decimal"
								autoComplete="off"
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="upsert-input-rate">Rate</Label>
							<Input
								id="upsert-input-rate"
								value={form.rate}
								onChange={(event) => {
									setField("rate", event.target.value);
									if (event.target.value) setField("amount", "");
								}}
								disabled={
									isSubmitting || form.input_kind !== "override" || Boolean(form.amount.trim())
								}
								inputMode="decimal"
								autoComplete="off"
							/>
							<p className="text-xs text-muted-foreground">
								Rates can only override an existing rate-based component.
							</p>
						</div>

						<div className="grid grid-cols-2 gap-3">
							<div className="grid gap-2">
								<Label htmlFor="upsert-input-service-start">Service Period Start</Label>
								<DatePicker
									id="upsert-input-service-start"
									value={
										form.service_period_start ? parseApiDate(form.service_period_start) : undefined
									}
									onValueChange={(date) =>
										setField("service_period_start", date ? toApiDate(date) : "")
									}
									disabled={isSubmitting}
									calendarProps={HISTORICAL_DATE_CALENDAR_PROPS}
									className="w-full"
									placeholder="Start date"
								/>
							</div>
							<div className="grid gap-2">
								<Label htmlFor="upsert-input-service-end">Service Period End</Label>
								<DatePicker
									id="upsert-input-service-end"
									value={
										form.service_period_end ? parseApiDate(form.service_period_end) : undefined
									}
									onValueChange={(date) =>
										setField("service_period_end", date ? toApiDate(date) : "")
									}
									disabled={isSubmitting}
									calendarProps={HISTORICAL_DATE_CALENDAR_PROPS}
									className="w-full"
									placeholder="End date"
								/>
							</div>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="upsert-input-reason">Reason</Label>
							<Input
								id="upsert-input-reason"
								value={form.reason}
								onChange={(event) => setField("reason", event.target.value)}
								disabled={isSubmitting}
								required
								autoComplete="off"
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
							{isSubmitting ? "Saving…" : isEdit ? "Save Changes" : "Add"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
