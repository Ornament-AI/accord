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
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import {
	periodLabel,
	RUN_TYPES,
	type RunType,
	runTypeLabel,
	useCreatePayrollRun,
	usePayrollPeriods,
} from "@/lib/api/payroll-runs";

type CreateRunDialogProps = {
	open: boolean;
	onOpenChange: (open: boolean) => void;
};

type FormState = {
	period_id: string;
	run_type: RunType;
};

const emptyForm = (): FormState => ({
	period_id: "",
	run_type: "regular",
});

export function CreateRunDialog({ open, onOpenChange }: CreateRunDialogProps) {
	const periodsQuery = usePayrollPeriods();
	const createRun = useCreatePayrollRun();
	const [form, setForm] = useState<FormState>(emptyForm);
	const [formError, setFormError] = useState<string | null>(null);

	const periods = periodsQuery.data ?? [];
	const defaultPeriodId = periods[0]?.id;

	useEffect(() => {
		if (!open) {
			setForm(emptyForm());
			setFormError(null);
		}
	}, [open]);

	useEffect(() => {
		if (!open || !defaultPeriodId) return;
		setForm((prev) => ({
			...prev,
			period_id: prev.period_id || defaultPeriodId,
		}));
	}, [open, defaultPeriodId]);

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setFormError(null);

		if (!form.period_id) {
			setFormError("Select a payroll period.");
			return;
		}

		try {
			await createRun.mutateAsync({
				period_id: form.period_id,
				run_type: form.run_type,
			});
			onOpenChange(false);
		} catch (error) {
			setFormError(error instanceof Error ? error.message : "Failed to create payroll run.");
		}
	};

	const isSubmitting = createRun.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-md">
				<DialogHeader>
					<DialogTitle>New pay run</DialogTitle>
					<DialogDescription>
						Create a payroll run for an existing period. Regular runs are unique per period.
					</DialogDescription>
				</DialogHeader>

				<form className="grid gap-4" onSubmit={(event) => void handleSubmit(event)}>
					<div className="grid gap-2">
						<Label htmlFor="create-run-period">Period</Label>
						<Select
							value={form.period_id || undefined}
							onValueChange={(value) => setForm((prev) => ({ ...prev, period_id: value ?? "" }))}
							disabled={isSubmitting || periods.length === 0}
						>
							<SelectTrigger id="create-run-period" className="w-full">
								<SelectValue placeholder="Select period" />
							</SelectTrigger>
							<SelectContent>
								{periods.map((period) => (
									<SelectItem key={period.id} value={period.id}>
										{periodLabel(period.period_year, period.period_month)}
									</SelectItem>
								))}
							</SelectContent>
						</Select>
					</div>

					<div className="grid gap-2">
						<Label htmlFor="create-run-type">Run type</Label>
						<Select
							value={form.run_type}
							onValueChange={(value) =>
								setForm((prev) => ({ ...prev, run_type: value as RunType }))
							}
							disabled={isSubmitting}
						>
							<SelectTrigger id="create-run-type" className="w-full">
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								{RUN_TYPES.map((runType) => (
									<SelectItem key={runType} value={runType}>
										{runTypeLabel(runType)}
									</SelectItem>
								))}
							</SelectContent>
						</Select>
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
						<Button type="submit" disabled={isSubmitting || periods.length === 0}>
							{isSubmitting ? "Creating…" : "Create run"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
