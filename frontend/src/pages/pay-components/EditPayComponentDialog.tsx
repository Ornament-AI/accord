import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
	classificationLabel,
	type PayComponentResponse,
	useUpdatePayComponent,
} from "@/lib/api/pay-setup";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { ApiError } from "@/lib/errors";

type EditPayComponentDialogProps = {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	component: PayComponentResponse | null;
};

type FormState = {
	name: string;
	display_order: string;
	is_active: boolean;
};

export function EditPayComponentDialog({
	open,
	onOpenChange,
	component,
}: EditPayComponentDialogProps) {
	const updateComponent = useUpdatePayComponent();
	const [form, setForm] = useState<FormState>({
		name: "",
		display_order: "0",
		is_active: true,
	});
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (open && component) {
			setForm({
				name: component.name,
				display_order: String(component.display_order),
				is_active: component.is_active,
			});
			setFormError(null);
		}
	}, [open, component]);

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		if (!component) return;
		setFormError(null);

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
			await updateComponent.mutateAsync({
				componentId: component.id,
				body: {
					name: form.name.trim(),
					display_order: displayOrder,
					is_active: form.is_active,
				},
			});
			onOpenChange(false);
		} catch (error) {
			setFormError(
				error instanceof ApiError
					? error.detail
					: error instanceof Error
						? error.message
						: "Failed to update pay component.",
			);
		}
	};

	const isSubmitting = updateComponent.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.compactForm}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>Edit pay component</DialogTitle>
					<DialogDescription>
						Update name, display order, or active status. Code and classification are fixed.
					</DialogDescription>
				</DialogHeader>

				{component ? (
					<form
						className="flex min-h-0 flex-1 flex-col"
						onSubmit={(event) => void handleSubmit(event)}
					>
						<DialogBody className="grid gap-4 pb-8">
							<div className="grid gap-2">
								<Label htmlFor="edit-pc-code">Code</Label>
								<Input id="edit-pc-code" value={component.code} readOnly disabled />
							</div>

							<div className="grid gap-2">
								<Label htmlFor="edit-pc-classification">Classification</Label>
								<Input
									id="edit-pc-classification"
									value={classificationLabel(component.classification)}
									readOnly
									disabled
								/>
							</div>

							<div className="grid gap-2">
								<Label htmlFor="edit-pc-name">Name</Label>
								<Input
									id="edit-pc-name"
									value={form.name}
									onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
									disabled={isSubmitting}
								/>
							</div>

							<div className="grid gap-2">
								<Label htmlFor="edit-pc-display-order">Display order</Label>
								<Input
									id="edit-pc-display-order"
									type="number"
									value={form.display_order}
									onChange={(event) =>
										setForm((prev) => ({ ...prev, display_order: event.target.value }))
									}
									disabled={isSubmitting}
								/>
							</div>

							<div className="flex items-center gap-2">
								<Checkbox
									id="edit-pc-is-active"
									checked={form.is_active}
									onCheckedChange={(checked) =>
										setForm((prev) => ({ ...prev, is_active: checked === true }))
									}
									disabled={isSubmitting}
								/>
								<Label htmlFor="edit-pc-is-active">Active</Label>
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
								{isSubmitting ? "Saving…" : "Save changes"}
							</Button>
						</DialogFooter>
					</form>
				) : null}
			</DialogContent>
		</Dialog>
	);
}
