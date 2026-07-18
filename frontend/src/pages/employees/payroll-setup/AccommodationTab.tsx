import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
	Dialog,
	DialogBody,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
	type AccommodationResponse,
	QUARTERS_LOCATIONS,
	type QuartersLocation,
	quartersLocationLabel,
	useAccommodation,
	useCreateAccommodation,
	useCreateAccommodationChargeVersion,
} from "@/lib/api/pay-setup";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { ApiError, getErrorMessage } from "@/lib/errors";

import { validateNonNegativeMoney, validatePositiveMoney } from "./money";

type AccommodationTabProps = {
	employeeId: string;
	asOf: string;
	canManage: boolean;
};

export function AccommodationTab({ employeeId, asOf, canManage }: AccommodationTabProps) {
	const accommodationQuery = useAccommodation(employeeId, asOf);
	const [addOpen, setAddOpen] = useState(false);
	const [versionTarget, setVersionTarget] = useState<AccommodationResponse | null>(null);

	const rows = accommodationQuery.data ?? [];

	return (
		<div className="grid gap-4" data-testid="accommodation-tab">
			<div className="flex flex-wrap items-center justify-between gap-2">
				<h3 className="text-sm font-medium">Accommodation</h3>
				{canManage ? (
					<Button size="sm" onClick={() => setAddOpen(true)}>
						Add assignment
					</Button>
				) : null}
			</div>

			{accommodationQuery.isLoading ? (
				<div className="grid gap-2">
					<Skeleton className="h-24 w-full" />
					<Skeleton className="h-24 w-full" />
				</div>
			) : null}

			{accommodationQuery.isError ? (
				<ErrorWithRetry
					message={getErrorMessage(accommodationQuery.error, "Failed to load accommodation.")}
					onRetry={() => void accommodationQuery.refetch()}
				/>
			) : null}

			{!accommodationQuery.isLoading && !accommodationQuery.isError ? (
				rows.length === 0 ? (
					<p className="text-sm text-muted-foreground">
						No accommodation assignments as of this date.
					</p>
				) : (
					<div className="grid gap-3">
						{rows.map((row) => (
							<Card key={row.id} size="sm" data-testid={`accommodation-card-${row.id}`}>
								<CardHeader className="border-b">
									<CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
										<span>
											{quartersLocationLabel(row.quarters_location)} — {row.quarters_identifier}
										</span>
										{canManage ? (
											<Button size="sm" variant="outline" onClick={() => setVersionTarget(row)}>
												New charge version
											</Button>
										) : null}
									</CardTitle>
								</CardHeader>
								<CardContent className="grid gap-3 pt-4 text-sm">
									<div className="grid grid-cols-[10rem_1fr] gap-2">
										<dt className="text-muted-foreground">License fee</dt>
										<dd data-testid="accommodation-license-fee">{row.license_fee ?? "—"}</dd>
									</div>
									<div className="grid gap-1">
										<div className="grid grid-cols-[10rem_1fr] gap-2">
											<dt className="text-muted-foreground">Foregone HRA</dt>
											<dd data-testid="accommodation-foregone-hra">
												{row.informational_hra_foregone ?? "—"}
											</dd>
										</div>
										<p
											className="text-xs text-muted-foreground"
											data-testid="accommodation-foregone-caption"
										>
											Informational only — not a payroll charge. Shown for reference against the
											license fee.
										</p>
									</div>
								</CardContent>
							</Card>
						))}
					</div>
				)
			) : null}

			{canManage ? (
				<>
					<AddAssignmentDialog open={addOpen} onOpenChange={setAddOpen} employeeId={employeeId} />
					<NewChargeVersionDialog
						open={Boolean(versionTarget)}
						onOpenChange={(open) => {
							if (!open) setVersionTarget(null);
						}}
						employeeId={employeeId}
						assignment={versionTarget}
					/>
				</>
			) : null}
		</div>
	);
}

type AddAssignmentForm = {
	quarters_location: QuartersLocation;
	quarters_identifier: string;
	effective_from: string;
	license_fee: string;
	informational_hra_foregone: string;
};

const emptyAddForm = (): AddAssignmentForm => ({
	quarters_location: "mumbai",
	quarters_identifier: "",
	effective_from: "",
	license_fee: "",
	informational_hra_foregone: "",
});

function AddAssignmentDialog({
	open,
	onOpenChange,
	employeeId,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	employeeId: string;
}) {
	const createAssignment = useCreateAccommodation(employeeId);
	const [form, setForm] = useState<AddAssignmentForm>(emptyAddForm);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyAddForm());
			setFormError(null);
		}
	}, [open]);

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setFormError(null);

		if (!form.quarters_identifier.trim()) {
			setFormError("Quarters identifier is required.");
			return;
		}
		if (!form.effective_from) {
			setFormError("Effective from is required.");
			return;
		}

		const licenseError = validatePositiveMoney(form.license_fee, "License fee");
		if (licenseError) {
			setFormError(licenseError);
			return;
		}

		const foregone = form.informational_hra_foregone.trim();
		if (foregone) {
			const foregoneError = validateNonNegativeMoney(foregone, "Informational foregone HRA");
			if (foregoneError) {
				setFormError(foregoneError);
				return;
			}
		}

		try {
			await createAssignment.mutateAsync({
				quarters_location: form.quarters_location,
				quarters_identifier: form.quarters_identifier.trim(),
				charge: {
					effective_from: form.effective_from,
					license_fee: form.license_fee.trim(),
					informational_hra_foregone: foregone || null,
				},
			});
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 422) {
				setFormError(error.detail || "Validation failed.");
				return;
			}
			setFormError(getErrorMessage(error, "Failed to create accommodation assignment."));
		}
	};

	const isSubmitting = createAssignment.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.form}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>Add assignment</DialogTitle>
					<DialogDescription>
						Assign government quarters and the initial license fee charge.
					</DialogDescription>
				</DialogHeader>

				<form
					className="flex min-h-0 flex-1 flex-col"
					onSubmit={(event) => void handleSubmit(event)}
				>
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="add-acc-location">Quarters location</Label>
							<Select
								value={form.quarters_location}
								onValueChange={(value) =>
									setForm((prev) => ({
										...prev,
										quarters_location: value as QuartersLocation,
									}))
								}
								disabled={isSubmitting}
							>
								<SelectTrigger id="add-acc-location" className="w-full">
									<SelectValue>
										{(value: QuartersLocation | null) =>
											value ? quartersLocationLabel(value) : "Select quarters location"
										}
									</SelectValue>
								</SelectTrigger>
								<SelectContent>
									{QUARTERS_LOCATIONS.map((location) => (
										<SelectItem key={location} value={location}>
											{quartersLocationLabel(location)}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-acc-identifier">Quarters identifier</Label>
							<Input
								id="add-acc-identifier"
								value={form.quarters_identifier}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, quarters_identifier: event.target.value }))
								}
								disabled={isSubmitting}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-acc-effective-from">Effective from</Label>
							<Input
								id="add-acc-effective-from"
								type="date"
								value={form.effective_from}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, effective_from: event.target.value }))
								}
								disabled={isSubmitting}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-acc-license-fee">License fee</Label>
							<Input
								id="add-acc-license-fee"
								inputMode="decimal"
								value={form.license_fee}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, license_fee: event.target.value }))
								}
								disabled={isSubmitting}
								placeholder="0.00"
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-acc-foregone-hra">Informational foregone HRA (optional)</Label>
							<Input
								id="add-acc-foregone-hra"
								inputMode="decimal"
								value={form.informational_hra_foregone}
								onChange={(event) =>
									setForm((prev) => ({
										...prev,
										informational_hra_foregone: event.target.value,
									}))
								}
								disabled={isSubmitting}
								placeholder="0.00"
							/>
							<p className="text-xs text-muted-foreground">
								Informational only — not deducted as a charge.
							</p>
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
							{isSubmitting ? "Creating…" : "Add assignment"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

type ChargeVersionForm = {
	effective_from: string;
	license_fee: string;
	informational_hra_foregone: string;
	change_reason: string;
};

const emptyChargeForm = (): ChargeVersionForm => ({
	effective_from: "",
	license_fee: "",
	informational_hra_foregone: "",
	change_reason: "",
});

function NewChargeVersionDialog({
	open,
	onOpenChange,
	employeeId,
	assignment,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	employeeId: string;
	assignment: AccommodationResponse | null;
}) {
	const createVersion = useCreateAccommodationChargeVersion(employeeId);
	const [form, setForm] = useState<ChargeVersionForm>(emptyChargeForm);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyChargeForm());
			setFormError(null);
		}
	}, [open]);

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		if (!assignment) return;
		setFormError(null);

		if (!form.effective_from) {
			setFormError("Effective from is required.");
			return;
		}

		const licenseError = validatePositiveMoney(form.license_fee, "License fee");
		if (licenseError) {
			setFormError(licenseError);
			return;
		}

		const foregone = form.informational_hra_foregone.trim();
		if (foregone) {
			const foregoneError = validateNonNegativeMoney(foregone, "Informational foregone HRA");
			if (foregoneError) {
				setFormError(foregoneError);
				return;
			}
		}

		try {
			await createVersion.mutateAsync({
				assignmentId: assignment.id,
				body: {
					effective_from: form.effective_from,
					license_fee: form.license_fee.trim(),
					informational_hra_foregone: foregone || null,
					change_reason: form.change_reason.trim() || null,
				},
			});
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 422) {
				setFormError(error.detail || "Validation failed.");
				return;
			}
			setFormError(getErrorMessage(error, "Failed to create charge version."));
		}
	};

	const isSubmitting = createVersion.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.form}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>New charge version</DialogTitle>
					<DialogDescription>
						Create a new license fee charge version for this assignment.
					</DialogDescription>
				</DialogHeader>

				<form
					className="flex min-h-0 flex-1 flex-col"
					onSubmit={(event) => void handleSubmit(event)}
				>
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="ncv-effective-from">Effective from</Label>
							<Input
								id="ncv-effective-from"
								type="date"
								value={form.effective_from}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, effective_from: event.target.value }))
								}
								disabled={isSubmitting}
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="ncv-license-fee">License fee</Label>
							<Input
								id="ncv-license-fee"
								inputMode="decimal"
								value={form.license_fee}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, license_fee: event.target.value }))
								}
								disabled={isSubmitting}
								placeholder="0.00"
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="ncv-foregone-hra">Informational foregone HRA (optional)</Label>
							<Input
								id="ncv-foregone-hra"
								inputMode="decimal"
								value={form.informational_hra_foregone}
								onChange={(event) =>
									setForm((prev) => ({
										...prev,
										informational_hra_foregone: event.target.value,
									}))
								}
								disabled={isSubmitting}
								placeholder="0.00"
							/>
							<p className="text-xs text-muted-foreground">
								Informational only — not deducted as a charge.
							</p>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="ncv-change-reason">Change reason (optional)</Label>
							<Textarea
								id="ncv-change-reason"
								value={form.change_reason}
								onChange={(event) =>
									setForm((prev) => ({ ...prev, change_reason: event.target.value }))
								}
								disabled={isSubmitting}
								rows={2}
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
							{isSubmitting ? "Saving…" : "Create version"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
