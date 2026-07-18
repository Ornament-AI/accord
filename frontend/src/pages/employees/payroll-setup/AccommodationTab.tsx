import { type FormEvent, useEffect, useState } from "react";

import { InfoTip } from "@/components/info-tip";
import { isInteractiveRowTarget } from "@/components/table-interactions";
import { Button } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
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
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { parseApiDate, toApiDate } from "@/lib/api/employees";
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

const FOREGONE_HRA_INFO =
	"Informational only — not a payroll charge. Shown for reference against the license fee.";
const FOREGONE_HRA_FORM_INFO = "Informational only — not deducted as a charge.";

type AccommodationTabProps = {
	employeeId: string;
	asOf: string;
	canManage: boolean;
	createOpen: boolean;
	onCreateOpenChange: (open: boolean) => void;
};

export function AccommodationTab({
	employeeId,
	asOf,
	canManage,
	createOpen,
	onCreateOpenChange,
}: AccommodationTabProps) {
	const accommodationQuery = useAccommodation(employeeId, asOf);
	const [versionTarget, setVersionTarget] = useState<AccommodationResponse | null>(null);

	const rows = accommodationQuery.data ?? [];

	return (
		<div className="grid gap-4" data-testid="accommodation-tab">
			{accommodationQuery.isLoading ? (
				<div className="grid gap-2">
					<Skeleton className="h-10 w-full" />
					<Skeleton className="h-10 w-full" />
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
					<Table>
						<TableHeader>
							<TableRow>
								<TableHead>Location</TableHead>
								<TableHead className="text-right">License Fee</TableHead>
								<TableHead className="text-right">
									<Tooltip>
										<TooltipTrigger
											render={
												<span data-testid="accommodation-foregone-caption" className="cursor-help">
													Foregone HRA
												</span>
											}
										/>
										<TooltipContent side="top">{FOREGONE_HRA_INFO}</TooltipContent>
									</Tooltip>
								</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{rows.map((row) => (
								<TableRow
									key={row.id}
									data-testid={`accommodation-row-${row.id}`}
									className={canManage ? "cursor-pointer" : undefined}
									onClick={(event) => {
										if (!canManage || isInteractiveRowTarget(event.target, event.currentTarget)) {
											return;
										}
										setVersionTarget(row);
									}}
								>
									<TableCell>
										{canManage ? (
											<button
												type="button"
												className="sr-only focus:not-sr-only focus:mb-1 focus:inline-flex focus:rounded-md focus:bg-background focus:px-2 focus:py-1 focus:ring-2 focus:ring-ring/35"
												onClick={() => setVersionTarget(row)}
											>
												Update Fee
											</button>
										) : null}
										{quartersLocationLabel(row.quarters_location)} — {row.quarters_identifier}
									</TableCell>
									<TableCell className="text-right" data-testid="accommodation-license-fee">
										{row.license_fee ?? "—"}
									</TableCell>
									<TableCell className="text-right" data-testid="accommodation-foregone-hra">
										{row.informational_hra_foregone ?? "—"}
									</TableCell>
								</TableRow>
							))}
						</TableBody>
					</Table>
				)
			) : null}

			{canManage ? (
				<>
					<AddAssignmentDialog
						open={createOpen}
						onOpenChange={onCreateOpenChange}
						employeeId={employeeId}
					/>
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

		const licenseError = validatePositiveMoney(form.license_fee, "License Fee");
		if (licenseError) {
			setFormError(licenseError);
			return;
		}

		const foregone = form.informational_hra_foregone.trim();
		if (foregone) {
			const foregoneError = validateNonNegativeMoney(foregone, "Informational Foregone HRA");
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
					<DialogTitle>Add Assignment</DialogTitle>
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
							<Label htmlFor="add-acc-location">Quarters Location</Label>
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
							<Label htmlFor="add-acc-identifier">Quarters Identifier</Label>
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
							<Label htmlFor="add-acc-effective-from">Effective From</Label>
							<DatePicker
								id="add-acc-effective-from"
								value={form.effective_from ? parseApiDate(form.effective_from) : undefined}
								onValueChange={(date) =>
									setForm((prev) => ({
										...prev,
										effective_from: date ? toApiDate(date) : "",
									}))
								}
								disabled={isSubmitting}
								className="w-full"
								placeholder="Effective From"
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="add-acc-license-fee">License Fee</Label>
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
							<div className="inline-flex items-center gap-1">
								<Label htmlFor="add-acc-foregone-hra">Informational Foregone HRA (Optional)</Label>
								<InfoTip text={FOREGONE_HRA_FORM_INFO} />
							</div>
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
							{isSubmitting ? "Creating…" : "Add"}
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
};

const emptyChargeForm = (): ChargeVersionForm => ({
	effective_from: "",
	license_fee: "",
	informational_hra_foregone: "",
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

		const licenseError = validatePositiveMoney(form.license_fee, "License Fee");
		if (licenseError) {
			setFormError(licenseError);
			return;
		}

		const foregone = form.informational_hra_foregone.trim();
		if (foregone) {
			const foregoneError = validateNonNegativeMoney(foregone, "Informational Foregone HRA");
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
					change_reason: null,
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
					<DialogTitle>New Charge Version</DialogTitle>
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
							<Label htmlFor="ncv-effective-from">Effective From</Label>
							<DatePicker
								id="ncv-effective-from"
								value={form.effective_from ? parseApiDate(form.effective_from) : undefined}
								onValueChange={(date) =>
									setForm((prev) => ({
										...prev,
										effective_from: date ? toApiDate(date) : "",
									}))
								}
								disabled={isSubmitting}
								className="w-full"
								placeholder="Effective From"
							/>
						</div>

						<div className="grid gap-2">
							<Label htmlFor="ncv-license-fee">License Fee</Label>
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
							<div className="inline-flex items-center gap-1">
								<Label htmlFor="ncv-foregone-hra">Informational Foregone HRA (Optional)</Label>
								<InfoTip text={FOREGONE_HRA_FORM_INFO} />
							</div>
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
