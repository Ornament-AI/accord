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
import { useEmployeesList } from "@/lib/api/employees";
import {
	INPUT_KINDS,
	type InputKind,
	inputKindLabel,
	type PayrollRunInputResponse,
	useUpsertPayrollRunInput,
} from "@/lib/api/payroll-runs";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { employeeEntityLabel } from "@/lib/entity-labels";

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
	reason: string;
	employee_search: string;
};

const emptyForm = (): FormState => ({
	employee_id: "",
	component_code: "",
	input_kind: "exception",
	amount: "",
	rate: "",
	reason: "",
	employee_search: "",
});

function formFromInput(input: PayrollRunInputResponse): FormState {
	return {
		employee_id: input.employee_id,
		component_code: input.component_code,
		input_kind: (INPUT_KINDS.includes(input.input_kind as InputKind)
			? input.input_kind
			: "exception") as InputKind,
		amount: input.amount ?? "",
		rate: input.rate ?? "",
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
	const [form, setForm] = useState<FormState>(emptyForm);
	const [formError, setFormError] = useState<string | null>(null);

	const employeesQuery = useEmployeesList({
		search: form.employee_search.trim() || null,
		page: 1,
		size: 20,
	});
	const employees = employeesQuery.data?.items ?? [];

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

		try {
			await upsertInput.mutateAsync({
				employeeId: form.employee_id,
				componentCode: form.component_code.trim(),
				body: {
					input_kind: form.input_kind,
					amount: form.amount.trim() === "" ? null : form.amount.trim(),
					rate: form.rate.trim() === "" ? null : form.rate.trim(),
					reason: form.reason.trim(),
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
										disabled={isSubmitting}
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
									<Label htmlFor="upsert-input-component">Component Code</Label>
									<Input
										id="upsert-input-component"
										value={form.component_code}
										onChange={(event) => setField("component_code", event.target.value)}
										disabled={isSubmitting}
										autoComplete="off"
									/>
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
								onValueChange={(value) => setField("input_kind", value as InputKind)}
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
								onChange={(event) => setField("amount", event.target.value)}
								disabled={isSubmitting}
								autoComplete="off"
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="upsert-input-rate">Rate</Label>
							<Input
								id="upsert-input-rate"
								value={form.rate}
								onChange={(event) => setField("rate", event.target.value)}
								disabled={isSubmitting}
								autoComplete="off"
							/>
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
							{isSubmitting ? "Saving…" : isEdit ? "Save changes" : "Add"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
