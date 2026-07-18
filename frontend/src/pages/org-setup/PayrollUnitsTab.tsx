import type { ColumnDef } from "@tanstack/react-table";
import { Landmark } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	type PayrollUnitCreate,
	type PayrollUnitResponse,
	useCreatePayrollUnit,
	usePayrollUnitsList,
	useUpdatePayrollUnit,
} from "@/lib/api/org-structure";
import { ApiError } from "@/lib/errors";

import { CatalogTab } from "./CatalogTab";

const columns: ColumnDef<PayrollUnitResponse>[] = [
	{ accessorKey: "code", header: "Code" },
	{ accessorKey: "name", header: "Name" },
];

type FormState = { code: string; name: string };
const emptyForm = (): FormState => ({ code: "", name: "" });

type PayrollUnitsTabProps = {
	canManage: boolean;
};

export function PayrollUnitsTab({ canManage }: PayrollUnitsTabProps) {
	const listQuery = usePayrollUnitsList();
	const [createOpen, setCreateOpen] = useState(false);
	const [editing, setEditing] = useState<PayrollUnitResponse | null>(null);

	return (
		<>
			<CatalogTab
				title="Payroll units"
				emptyDescription="Add a payroll unit to get started."
				icon={Landmark}
				columns={columns}
				data={listQuery.data}
				isLoading={listQuery.isLoading}
				isError={listQuery.isError}
				error={listQuery.error}
				onRetry={() => void listQuery.refetch()}
				canManage={canManage}
				onAdd={() => setCreateOpen(true)}
				onEdit={setEditing}
				addLabel="Add payroll unit"
				data-testid="payroll-units-tab"
			/>
			{canManage ? (
				<>
					<PayrollUnitFormDialog
						mode="create"
						open={createOpen}
						onOpenChange={setCreateOpen}
						item={null}
					/>
					<PayrollUnitFormDialog
						mode="edit"
						open={editing != null}
						onOpenChange={(open) => {
							if (!open) setEditing(null);
						}}
						item={editing}
					/>
				</>
			) : null}
		</>
	);
}

type FormDialogProps = {
	mode: "create" | "edit";
	open: boolean;
	onOpenChange: (open: boolean) => void;
	item: PayrollUnitResponse | null;
};

function PayrollUnitFormDialog({ mode, open, onOpenChange, item }: FormDialogProps) {
	const createMutation = useCreatePayrollUnit();
	const updateMutation = useUpdatePayrollUnit();
	const [form, setForm] = useState<FormState>(emptyForm);
	const [codeError, setCodeError] = useState<string | null>(null);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyForm());
			setCodeError(null);
			setFormError(null);
			return;
		}
		if (mode === "edit" && item) {
			setForm({ code: item.code, name: item.name });
		} else {
			setForm(emptyForm());
		}
		setCodeError(null);
		setFormError(null);
	}, [open, mode, item]);

	const isSubmitting = createMutation.isPending || updateMutation.isPending;
	const naturalKeyReadonly = mode === "edit";

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setCodeError(null);
		setFormError(null);

		if (mode === "create" && !form.code.trim()) {
			setCodeError("Code is required");
			return;
		}
		if (!form.name.trim()) {
			setFormError("Name is required.");
			return;
		}

		try {
			if (mode === "create") {
				const body: PayrollUnitCreate = {
					code: form.code.trim(),
					name: form.name.trim(),
				};
				await createMutation.mutateAsync(body);
			} else if (item) {
				await updateMutation.mutateAsync({
					payrollUnitId: item.id,
					body: { name: form.name.trim() },
				});
			}
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				setCodeError("This code is already in use");
				return;
			}
			setFormError(error instanceof Error ? error.message : "Unable to save payroll unit.");
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-md">
				<form onSubmit={(event) => void handleSubmit(event)} className="grid gap-4">
					<DialogHeader>
						<DialogTitle>
							{mode === "create" ? "Add payroll unit" : "Edit payroll unit"}
						</DialogTitle>
						<DialogDescription>
							{mode === "create"
								? "Create a payroll unit for this organization."
								: "Update payroll unit details. The code cannot be changed."}
						</DialogDescription>
					</DialogHeader>

					<div className="grid gap-2">
						<Label htmlFor="payroll-unit-code">Code</Label>
						<Input
							id="payroll-unit-code"
							value={form.code}
							onChange={(event) => {
								setForm((prev) => ({ ...prev, code: event.target.value }));
								setCodeError(null);
							}}
							disabled={isSubmitting || naturalKeyReadonly}
							readOnly={naturalKeyReadonly}
							aria-invalid={codeError ? true : undefined}
						/>
						{codeError ? <p className="text-sm text-destructive">{codeError}</p> : null}
					</div>

					<div className="grid gap-2">
						<Label htmlFor="payroll-unit-name">Name</Label>
						<Input
							id="payroll-unit-name"
							value={form.name}
							onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
							disabled={isSubmitting}
						/>
					</div>

					{formError ? <p className="text-sm text-destructive">{formError}</p> : null}

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
							{isSubmitting
								? "Saving…"
								: mode === "create"
									? "Create payroll unit"
									: "Save changes"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
