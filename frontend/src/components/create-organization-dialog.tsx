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
import { useAuth } from "@/contexts/AuthContext";
import { createOrganizationFromName } from "@/lib/create-organization";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";

type CreateOrganizationDialogProps = {
	open: boolean;
	onOpenChange: (open: boolean) => void;
};

export function CreateOrganizationDialog({ open, onOpenChange }: CreateOrganizationDialogProps) {
	const { createOrganization } = useAuth();
	const [name, setName] = useState("");
	const [formError, setFormError] = useState<string | null>(null);
	const [isSubmitting, setIsSubmitting] = useState(false);

	useEffect(() => {
		if (!open) {
			setName("");
			setFormError(null);
			setIsSubmitting(false);
		}
	}, [open]);

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setFormError(null);
		setIsSubmitting(true);
		try {
			await createOrganizationFromName(createOrganization, name);
			onOpenChange(false);
		} catch (error) {
			setFormError(
				error instanceof Error ? error.message : "Unable to create organization right now.",
			);
		} finally {
			setIsSubmitting(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.form}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>Create organization</DialogTitle>
					<DialogDescription>
						Set up a new organization. You will be signed into it after creation.
					</DialogDescription>
				</DialogHeader>

				<form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="create-org-name">Name</Label>
							<Input
								id="create-org-name"
								value={name}
								onChange={(event) => setName(event.target.value)}
								placeholder="Acme"
								autoComplete="organization"
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
							{isSubmitting ? "Creating…" : "Create organization"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
