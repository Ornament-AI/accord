import type { ColumnDef } from "@tanstack/react-table";
import { UsersRound } from "lucide-react";
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
	type EmployeeGroupCreate,
	type EmployeeGroupResponse,
	useCreateEmployeeGroup,
	useEmployeeGroupsList,
	useUpdateEmployeeGroup,
} from "@/lib/api/org-structure";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { ApiError } from "@/lib/errors";

import { CatalogTab } from "./CatalogTab";

const columns: ColumnDef<EmployeeGroupResponse>[] = [
	{ accessorKey: "name", header: "Name" },
	{ accessorKey: "code", header: "Code" },
];

type FormState = { code: string; name: string };
const emptyForm = (): FormState => ({ code: "", name: "" });

type EmployeeGroupsTabProps = {
	canManage: boolean;
	createOpen: boolean;
	onCreateOpenChange: (open: boolean) => void;
};

export function EmployeeGroupsTab({
	canManage,
	createOpen,
	onCreateOpenChange,
}: EmployeeGroupsTabProps) {
	const listQuery = useEmployeeGroupsList();
	const [editing, setEditing] = useState<EmployeeGroupResponse | null>(null);

	return (
		<>
			<CatalogTab
				title="Employee Groups"
				emptyDescription="Add an employee group to get started."
				icon={UsersRound}
				columns={columns}
				data={listQuery.data}
				isLoading={listQuery.isLoading}
				isError={listQuery.isError}
				error={listQuery.error}
				onRetry={() => void listQuery.refetch()}
				canManage={canManage}
				onAdd={() => onCreateOpenChange(true)}
				onEdit={setEditing}
				data-testid="employee-groups-tab"
			/>
			{canManage ? (
				<>
					<EmployeeGroupFormDialog
						mode="create"
						open={createOpen}
						onOpenChange={onCreateOpenChange}
						item={null}
					/>
					<EmployeeGroupFormDialog
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
	item: EmployeeGroupResponse | null;
};

function EmployeeGroupFormDialog({ mode, open, onOpenChange, item }: FormDialogProps) {
	const createMutation = useCreateEmployeeGroup();
	const updateMutation = useUpdateEmployeeGroup();
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
				const body: EmployeeGroupCreate = {
					code: form.code.trim(),
					name: form.name.trim(),
				};
				await createMutation.mutateAsync(body);
			} else if (item) {
				await updateMutation.mutateAsync({
					employeeGroupId: item.id,
					body: { name: form.name.trim() },
				});
			}
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				setCodeError("This code is already in use");
				return;
			}
			setFormError(error instanceof Error ? error.message : "Unable to save employee group.");
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.compactForm}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>
						{mode === "create" ? "Add Employee Group" : "Edit Employee Group"}
					</DialogTitle>
					<DialogDescription>
						{mode === "create"
							? "Create an employee group for this organization."
							: "Update employee group details. The code cannot be changed."}
					</DialogDescription>
				</DialogHeader>

				<form
					onSubmit={(event) => void handleSubmit(event)}
					className="flex min-h-0 flex-1 flex-col"
				>
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="employee-group-code">Code</Label>
							<Input
								id="employee-group-code"
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
							<Label htmlFor="employee-group-name">Name</Label>
							<Input
								id="employee-group-name"
								value={form.name}
								onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
								disabled={isSubmitting}
							/>
						</div>

						{formError ? <p className="text-sm text-destructive">{formError}</p> : null}
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
							{isSubmitting
								? "Saving…"
								: mode === "create"
									? "Create employee group"
									: "Save changes"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
