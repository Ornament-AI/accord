import { BriefcaseIcon as Briefcase } from "@phosphor-icons/react/dist/csr/Briefcase";
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
	type PostCreate,
	type PostResponse,
	useCreatePost,
	usePostsList,
	useUpdatePost,
} from "@/lib/api/org-structure";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { ApiError } from "@/lib/errors";

import { CatalogTab } from "./CatalogTab";

const columns: ColumnDef<PostResponse>[] = [
	{ accessorKey: "designation", header: "Designation" },
	{
		accessorKey: "pay_bill_heading",
		header: "Pay Bill Heading",
		cell: ({ row }) => row.original.pay_bill_heading ?? "—",
	},
	{ accessorKey: "class_name", header: "Class" },
	{
		accessorKey: "pay_scale",
		header: "Pay Scale",
		cell: ({ row }) => row.original.pay_scale ?? "—",
	},
	{
		accessorKey: "sanctioned_strength",
		header: "Sanctioned",
		cell: ({ row }) => row.original.sanctioned_strength ?? "—",
	},
	{
		accessorKey: "vacant_count",
		header: "Vacant",
		cell: ({ row }) => row.original.vacant_count ?? "—",
	},
];

type FormState = {
	designation: string;
	pay_bill_heading: string;
	class_name: string;
	sanctioned_strength: string;
	vacant_count: string;
	pay_scale: string;
	display_order: string;
};
const emptyForm = (): FormState => ({
	designation: "",
	pay_bill_heading: "",
	class_name: "",
	sanctioned_strength: "",
	vacant_count: "",
	pay_scale: "",
	display_order: "",
});

function optionalNonNegativeInteger(value: string, label: string): number | null {
	if (!value.trim()) return null;
	const parsed = Number(value);
	if (!Number.isInteger(parsed) || parsed < 0) {
		throw new Error(`${label} must be a whole number of zero or more.`);
	}
	return parsed;
}

type PostsTabProps = {
	canManage: boolean;
	createOpen: boolean;
	onCreateOpenChange: (open: boolean) => void;
};

export function PostsTab({ canManage, createOpen, onCreateOpenChange }: PostsTabProps) {
	const listQuery = usePostsList();
	const [editing, setEditing] = useState<PostResponse | null>(null);

	return (
		<>
			<CatalogTab
				title="Posts"
				icon={Briefcase}
				columns={columns}
				data={listQuery.data}
				isLoading={listQuery.isLoading}
				isError={listQuery.isError}
				error={listQuery.error}
				onRetry={() => void listQuery.refetch()}
				canManage={canManage}
				onEdit={setEditing}
				data-testid="posts-tab"
			/>
			{canManage ? (
				<>
					<PostFormDialog
						mode="create"
						open={createOpen}
						onOpenChange={onCreateOpenChange}
						item={null}
					/>
					<PostFormDialog
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
	item: PostResponse | null;
};

function PostFormDialog({ mode, open, onOpenChange, item }: FormDialogProps) {
	const createMutation = useCreatePost();
	const updateMutation = useUpdatePost();
	const [form, setForm] = useState<FormState>(emptyForm);
	const [designationError, setDesignationError] = useState<string | null>(null);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyForm());
			setDesignationError(null);
			setFormError(null);
			return;
		}
		if (mode === "edit" && item) {
			setForm({
				designation: item.designation,
				pay_bill_heading: item.pay_bill_heading ?? "",
				class_name: item.class_name,
				sanctioned_strength: item.sanctioned_strength?.toString() ?? "",
				vacant_count: item.vacant_count?.toString() ?? "",
				pay_scale: item.pay_scale ?? "",
				display_order: item.display_order?.toString() ?? "",
			});
		} else {
			setForm(emptyForm());
		}
		setDesignationError(null);
		setFormError(null);
	}, [open, mode, item]);

	const isSubmitting = createMutation.isPending || updateMutation.isPending;
	const naturalKeyReadonly = mode === "edit";

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setDesignationError(null);
		setFormError(null);

		if (mode === "create" && !form.designation.trim()) {
			setDesignationError("Designation is required");
			return;
		}
		if (!form.class_name.trim()) {
			setFormError("Class is required.");
			return;
		}

		try {
			const sanctionedStrength = optionalNonNegativeInteger(
				form.sanctioned_strength,
				"Sanctioned strength",
			);
			const vacantCount = optionalNonNegativeInteger(form.vacant_count, "Vacant count");
			const displayOrder = optionalNonNegativeInteger(form.display_order, "Display order");
			if (vacantCount !== null && sanctionedStrength === null) {
				setFormError("Enter sanctioned strength when vacant count is provided.");
				return;
			}
			if (vacantCount !== null && sanctionedStrength !== null && vacantCount > sanctionedStrength) {
				setFormError("Vacant count cannot exceed sanctioned strength.");
				return;
			}
			const canonicalFields = {
				pay_bill_heading: form.pay_bill_heading.trim() || null,
				sanctioned_strength: sanctionedStrength,
				vacant_count: vacantCount,
				pay_scale: form.pay_scale.trim() || null,
				display_order: displayOrder,
			};
			if (mode === "create") {
				const body: PostCreate = {
					designation: form.designation.trim(),
					class_name: form.class_name.trim(),
					...canonicalFields,
				};
				await createMutation.mutateAsync(body);
			} else if (item) {
				await updateMutation.mutateAsync({
					postId: item.id,
					body: { class_name: form.class_name.trim(), ...canonicalFields },
				});
			}
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				setDesignationError("This designation is already in use");
				return;
			}
			setFormError(error instanceof Error ? error.message : "Unable to save post.");
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.compactForm}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>{mode === "create" ? "Add Post" : "Edit Post"}</DialogTitle>
					<DialogDescription>
						{mode === "create"
							? "Create a post for this organization."
							: "Update post details. The designation cannot be changed."}
					</DialogDescription>
				</DialogHeader>

				<form
					onSubmit={(event) => void handleSubmit(event)}
					className="flex min-h-0 flex-1 flex-col"
				>
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="post-designation">Designation</Label>
							<Input
								id="post-designation"
								value={form.designation}
								onChange={(event) => {
									setForm((prev) => ({ ...prev, designation: event.target.value }));
									setDesignationError(null);
								}}
								disabled={isSubmitting || naturalKeyReadonly}
								readOnly={naturalKeyReadonly}
								aria-invalid={designationError ? true : undefined}
							/>
							{designationError ? (
								<p className="text-sm text-destructive">{designationError}</p>
							) : null}
						</div>

						<div className="grid gap-2">
							<Label htmlFor="post-pay-bill-heading">Pay Bill Heading</Label>
							<Input
								id="post-pay-bill-heading"
								value={form.pay_bill_heading}
								onChange={(event) =>
									setForm((previous) => ({
										...previous,
										pay_bill_heading: event.target.value,
									}))
								}
								disabled={isSubmitting}
								placeholder="Defaults to the designation"
							/>
						</div>

						<div className="grid grid-cols-2 gap-4">
							<div className="grid gap-2">
								<Label htmlFor="post-sanctioned-strength">Sanctioned Strength</Label>
								<Input
									id="post-sanctioned-strength"
									type="number"
									min="0"
									step="1"
									value={form.sanctioned_strength}
									onChange={(event) =>
										setForm((prev) => ({ ...prev, sanctioned_strength: event.target.value }))
									}
									disabled={isSubmitting}
								/>
							</div>
							<div className="grid gap-2">
								<Label htmlFor="post-vacant-count">Vacant Count</Label>
								<Input
									id="post-vacant-count"
									type="number"
									min="0"
									step="1"
									value={form.vacant_count}
									onChange={(event) =>
										setForm((prev) => ({ ...prev, vacant_count: event.target.value }))
									}
									disabled={isSubmitting}
								/>
							</div>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="post-pay-scale">Pay Scale</Label>
							<Input
								id="post-pay-scale"
								value={form.pay_scale}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, pay_scale: event.target.value }))
								}
								disabled={isSubmitting}
								placeholder="S-15: 41800–132300"
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="post-display-order">Display Order</Label>
							<Input
								id="post-display-order"
								type="number"
								min="0"
								step="1"
								value={form.display_order}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, display_order: event.target.value }))
								}
								disabled={isSubmitting}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="post-class-name">Class</Label>
							<Input
								id="post-class-name"
								value={form.class_name}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, class_name: event.target.value }))
								}
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
							{isSubmitting ? "Saving…" : mode === "create" ? "Create Post" : "Save Changes"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
