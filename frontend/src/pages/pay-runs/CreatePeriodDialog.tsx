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
import { useCreatePayrollPeriod } from "@/lib/api/payroll-runs";
import { ApiError } from "@/lib/errors";

type CreatePeriodDialogProps = {
	open: boolean;
	onOpenChange: (open: boolean) => void;
};

type FormState = {
	period_year: string;
	period_month: string;
};

function emptyForm(): FormState {
	const now = new Date();
	return {
		period_year: String(now.getFullYear()),
		period_month: String(now.getMonth() + 1),
	};
}

export function CreatePeriodDialog({ open, onOpenChange }: CreatePeriodDialogProps) {
	const createPeriod = useCreatePayrollPeriod();
	const [form, setForm] = useState<FormState>(emptyForm);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyForm());
			setFormError(null);
		}
	}, [open]);

	const setField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setFormError(null);

		const year = Number(form.period_year);
		const month = Number(form.period_month);
		if (!Number.isInteger(year) || year < 2000 || year > 2100) {
			setFormError("Enter a valid year.");
			return;
		}
		if (!Number.isInteger(month) || month < 1 || month > 12) {
			setFormError("Month must be between 1 and 12.");
			return;
		}

		try {
			await createPeriod.mutateAsync({ period_year: year, period_month: month });
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				setFormError(error.detail || "A payroll period for this year and month already exists.");
				return;
			}
			setFormError(error instanceof Error ? error.message : "Failed to create payroll period.");
		}
	};

	const isSubmitting = createPeriod.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-md">
				<DialogHeader>
					<DialogTitle>New payroll period</DialogTitle>
					<DialogDescription>
						Create a payroll period for a calendar month. Duplicate year/month combinations are
						rejected.
					</DialogDescription>
				</DialogHeader>

				<form className="grid gap-4" onSubmit={(event) => void handleSubmit(event)}>
					<div className="grid gap-2">
						<Label htmlFor="create-period-year">Year</Label>
						<Input
							id="create-period-year"
							type="number"
							value={form.period_year}
							onChange={(event) => setField("period_year", event.target.value)}
							disabled={isSubmitting}
							autoComplete="off"
						/>
					</div>

					<div className="grid gap-2">
						<Label htmlFor="create-period-month">Month</Label>
						<Input
							id="create-period-month"
							type="number"
							min={1}
							max={12}
							value={form.period_month}
							onChange={(event) => setField("period_month", event.target.value)}
							disabled={isSubmitting}
							autoComplete="off"
						/>
					</div>

					{formError ? (
						<p className="text-sm text-destructive" role="alert">
							{formError}
						</p>
					) : null}

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
							{isSubmitting ? "Creating…" : "Create period"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
