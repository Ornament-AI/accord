import { BuildingsIcon as Building2 } from "@phosphor-icons/react/dist/csr/Buildings";
import type { ColumnDef } from "@tanstack/react-table";
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
import {
	type OfficeCreate,
	type OfficeJurisdiction,
	type OfficeResponse,
	useCreateOffice,
	useOfficesList,
	useUpdateOffice,
} from "@/lib/api/org-structure";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";

import { CatalogTab } from "./CatalogTab";

const JURISDICTIONS: { value: OfficeJurisdiction; label: string }[] = [
	{ value: "mumbai", label: "Mumbai" },
	{ value: "nagpur", label: "Nagpur" },
	{ value: "worli", label: "Worli" },
	{ value: "other", label: "Other" },
];

const columns: ColumnDef<OfficeResponse>[] = [
	{ accessorKey: "name", header: "Name" },
	{
		accessorKey: "jurisdiction",
		header: "Jurisdiction",
		cell: ({ row }) => {
			const value = row.original.jurisdiction;
			return JURISDICTIONS.find((item) => item.value === value)?.label ?? value;
		},
	},
];

type OfficeFormState = {
	name: string;
	jurisdiction: OfficeJurisdiction;
};

const emptyForm = (): OfficeFormState => ({
	name: "",
	jurisdiction: "mumbai",
});

type OfficesTabProps = {
	canManage: boolean;
	createOpen: boolean;
	onCreateOpenChange: (open: boolean) => void;
};

export function OfficesTab({ canManage, createOpen, onCreateOpenChange }: OfficesTabProps) {
	const listQuery = useOfficesList();
	const [editing, setEditing] = useState<OfficeResponse | null>(null);

	return (
		<>
			<CatalogTab
				title="Offices"
				icon={Building2}
				columns={columns}
				data={listQuery.data}
				isLoading={listQuery.isLoading}
				isError={listQuery.isError}
				error={listQuery.error}
				onRetry={() => void listQuery.refetch()}
				canManage={canManage}
				onEdit={setEditing}
				data-testid="offices-tab"
			/>
			{canManage ? (
				<>
					<OfficeFormDialog
						mode="create"
						open={createOpen}
						onOpenChange={onCreateOpenChange}
						office={null}
					/>
					<OfficeFormDialog
						mode="edit"
						open={editing != null}
						onOpenChange={(open) => {
							if (!open) setEditing(null);
						}}
						office={editing}
					/>
				</>
			) : null}
		</>
	);
}

type OfficeFormDialogProps = {
	mode: "create" | "edit";
	open: boolean;
	onOpenChange: (open: boolean) => void;
	office: OfficeResponse | null;
};

function OfficeFormDialog({ mode, open, onOpenChange, office }: OfficeFormDialogProps) {
	const createOffice = useCreateOffice();
	const updateOffice = useUpdateOffice();
	const [form, setForm] = useState<OfficeFormState>(emptyForm);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyForm());
			setFormError(null);
			return;
		}
		if (mode === "edit" && office) {
			setForm({
				name: office.name,
				jurisdiction: (JURISDICTIONS.find((item) => item.value === office.jurisdiction)?.value ??
					"other") as OfficeJurisdiction,
			});
		} else {
			setForm(emptyForm());
		}
		setFormError(null);
	}, [open, mode, office]);

	const isSubmitting = createOffice.isPending || updateOffice.isPending;

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setFormError(null);

		if (!form.name.trim()) {
			setFormError("Name is required.");
			return;
		}

		try {
			if (mode === "create") {
				const body: OfficeCreate = {
					name: form.name.trim(),
					jurisdiction: form.jurisdiction,
				};
				await createOffice.mutateAsync(body);
			} else if (office) {
				await updateOffice.mutateAsync({
					officeId: office.id,
					body: {
						name: form.name.trim(),
						jurisdiction: form.jurisdiction,
					},
				});
			}
			onOpenChange(false);
		} catch (error) {
			setFormError(error instanceof Error ? error.message : "Unable to save office.");
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.compactForm}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>{mode === "create" ? "Add Office" : "Edit Office"}</DialogTitle>
					<DialogDescription>
						{mode === "create"
							? "Create an office for this organization."
							: "Update office details."}
					</DialogDescription>
				</DialogHeader>

				<form
					onSubmit={(event) => void handleSubmit(event)}
					className="flex min-h-0 flex-1 flex-col"
				>
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="office-name">Name</Label>
							<Input
								id="office-name"
								value={form.name}
								onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
								disabled={isSubmitting}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="office-jurisdiction">Jurisdiction</Label>
							<Select
								value={form.jurisdiction}
								onValueChange={(value) =>
									setForm((prev) => ({
										...prev,
										jurisdiction: value as OfficeJurisdiction,
									}))
								}
								disabled={isSubmitting}
							>
								<SelectTrigger id="office-jurisdiction" className="w-full">
									<SelectValue>
										{(value: OfficeJurisdiction | null) =>
											JURISDICTIONS.find((item) => item.value === value)?.label ??
											"Select jurisdiction"
										}
									</SelectValue>
								</SelectTrigger>
								<SelectContent>
									{JURISDICTIONS.map((item) => (
										<SelectItem key={item.value} value={item.value}>
											{item.label}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
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
							{isSubmitting ? "Saving…" : mode === "create" ? "Create Office" : "Save Changes"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
