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
	CLASSIFICATIONS,
	type Classification,
	classificationLabel,
	useCreatePayComponent,
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
	display_order: string;
};

const emptyForm = (): FormState => ({
	code: "",
	name: "",
	classification: "earning",
	display_order: "0",
});

export function CreatePayComponentDialog({ open, onOpenChange }: CreatePayComponentDialogProps) {
	const createComponent = useCreatePayComponent();
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
				display_order: displayOrder,
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
								onValueChange={(value) => setField("classification", value as Classification)}
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
							<Label htmlFor="create-pc-display-order">Display Order</Label>
							<Input
								id="create-pc-display-order"
								type="number"
								value={form.display_order}
								onChange={(event) => setField("display_order", event.target.value)}
								disabled={isSubmitting}
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
							{isSubmitting ? "Creating…" : "Create component"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
