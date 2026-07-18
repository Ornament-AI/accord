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
import { Textarea } from "@/components/ui/textarea";
import {
	type BankVersionResponse,
	type EmployeeVersionKind,
	type GpfJurisdiction,
	type PayVersionResponse,
	type PostingVersionResponse,
	type ProfileVersionResponse,
	type RetirementRegime,
	todayApiDate,
	useCreateEmployeeVersion,
} from "@/lib/api/employees";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { ApiError } from "@/lib/errors";

type ScheduleChangeDialogProps = {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	employeeId: string;
	kind: EmployeeVersionKind;
	activeProfile?: ProfileVersionResponse | null;
	activePosting?: PostingVersionResponse | null;
	activePay?: PayVersionResponse | null;
	activeBank?: BankVersionResponse | null;
};

const kindLabels: Record<EmployeeVersionKind, string> = {
	profile: "Profile",
	posting: "Posting",
	pay: "Pay",
	bank: "Bank",
};

export function ScheduleChangeDialog({
	open,
	onOpenChange,
	employeeId,
	kind,
	activeProfile,
	activePosting,
	activePay,
	activeBank,
}: ScheduleChangeDialogProps) {
	const createVersion = useCreateEmployeeVersion(employeeId);
	const [effectiveFrom, setEffectiveFrom] = useState(todayApiDate());
	const [changeReason, setChangeReason] = useState("");
	const [overlapError, setOverlapError] = useState<string | null>(null);
	const [formError, setFormError] = useState<string | null>(null);

	// Profile fields
	const [name, setName] = useState("");
	const [sevarthId, setSevarthId] = useState("");
	const [retirementRegime, setRetirementRegime] = useState<RetirementRegime>("nps");
	const [gpfJurisdiction, setGpfJurisdiction] = useState<GpfJurisdiction | "">("");
	const [pan, setPan] = useState("");
	const [pran, setPran] = useState("");
	const [gpfAccountNumber, setGpfAccountNumber] = useState("");
	const [epfNumber, setEpfNumber] = useState("");
	const [dateOfBirth, setDateOfBirth] = useState("");
	const [dateOfJoining, setDateOfJoining] = useState("");
	const [gpfJurisdictionError, setGpfJurisdictionError] = useState<string | null>(null);

	// Posting fields
	const [officeId, setOfficeId] = useState("");
	const [payrollUnitId, setPayrollUnitId] = useState("");
	const [postId, setPostId] = useState("");
	const [employeeGroupId, setEmployeeGroupId] = useState("");

	// Pay fields
	const [payMatrixLevel, setPayMatrixLevel] = useState("");
	const [basicPay, setBasicPay] = useState("");

	// Bank fields
	const [accountNumber, setAccountNumber] = useState("");
	const [ifsc, setIfsc] = useState("");
	const [bankName, setBankName] = useState("");
	const [branch, setBranch] = useState("");

	useEffect(() => {
		if (!open) return;
		setEffectiveFrom(todayApiDate());
		setChangeReason("");
		setOverlapError(null);
		setFormError(null);
		setGpfJurisdictionError(null);

		if (kind === "profile" && activeProfile) {
			setName(activeProfile.name);
			setSevarthId(activeProfile.sevarth_id);
			setRetirementRegime((activeProfile.retirement_regime as RetirementRegime) || "nps");
			setGpfJurisdiction((activeProfile.gpf_jurisdiction as GpfJurisdiction) || "");
			setPan(activeProfile.pan ?? "");
			setPran(activeProfile.pran ?? "");
			setGpfAccountNumber(activeProfile.gpf_account_number ?? "");
			setEpfNumber(activeProfile.epf_number ?? "");
			setDateOfBirth(activeProfile.date_of_birth);
			setDateOfJoining(activeProfile.date_of_joining);
		}
		if (kind === "posting" && activePosting) {
			setOfficeId(activePosting.office_id);
			setPayrollUnitId(activePosting.payroll_unit_id);
			setPostId(activePosting.post_id);
			setEmployeeGroupId(activePosting.employee_group_id ?? "");
		}
		if (kind === "pay" && activePay) {
			setPayMatrixLevel(activePay.pay_matrix_level);
			setBasicPay(activePay.basic_pay);
		}
		if (kind === "bank" && activeBank) {
			setAccountNumber(activeBank.account_number);
			setIfsc(activeBank.ifsc);
			setBankName(activeBank.bank_name);
			setBranch(activeBank.branch);
		}
	}, [open, kind, activeProfile, activePosting, activePay, activeBank]);

	const buildBody = (): Record<string, unknown> | null => {
		const base = {
			effective_from: effectiveFrom,
			change_reason: changeReason.trim() || null,
		};

		if (kind === "profile") {
			if (retirementRegime === "gpf" && !gpfJurisdiction) {
				setGpfJurisdictionError("GPF jurisdiction is required when regime is GPF");
				return null;
			}
			return {
				...base,
				name: name.trim(),
				sevarth_id: sevarthId.trim(),
				retirement_regime: retirementRegime,
				gpf_jurisdiction: retirementRegime === "gpf" ? gpfJurisdiction : null,
				pan: pan.trim() || null,
				pran: pran.trim() || null,
				gpf_account_number: gpfAccountNumber.trim() || null,
				epf_number: epfNumber.trim() || null,
				date_of_birth: dateOfBirth,
				date_of_joining: dateOfJoining,
			};
		}
		if (kind === "posting") {
			return {
				...base,
				office_id: officeId.trim(),
				payroll_unit_id: payrollUnitId.trim(),
				post_id: postId.trim(),
				employee_group_id: employeeGroupId.trim() || null,
			};
		}
		if (kind === "pay") {
			return {
				...base,
				pay_matrix_level: payMatrixLevel.trim(),
				basic_pay: basicPay.trim(),
			};
		}
		return {
			...base,
			account_number: accountNumber.trim(),
			ifsc: ifsc.trim(),
			bank_name: bankName.trim(),
			branch: branch.trim(),
			is_primary_salary: true,
		};
	};

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setOverlapError(null);
		setFormError(null);
		setGpfJurisdictionError(null);

		const body = buildBody();
		if (!body) return;

		try {
			await createVersion.mutateAsync({ kind, body });
			onOpenChange(false);
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				setOverlapError(error.message || "Version periods overlap.");
				return;
			}
			setFormError(error instanceof Error ? error.message : "Unable to schedule change.");
		}
	};

	const isSubmitting = createVersion.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.form}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>Schedule {kindLabels[kind].toLowerCase()} change</DialogTitle>
					<DialogDescription>
						Append a new {kindLabels[kind].toLowerCase()} version with a new effective date.
					</DialogDescription>
				</DialogHeader>
				<form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
					<DialogBody className="grid gap-4 pb-8">
						<div className="grid gap-2">
							<Label htmlFor="schedule-effective-from">Effective from</Label>
							<Input
								id="schedule-effective-from"
								type="date"
								value={effectiveFrom}
								onChange={(event) => setEffectiveFrom(event.target.value)}
								disabled={isSubmitting}
							/>
						</div>

						{kind === "profile" ? (
							<>
								<div className="grid gap-2">
									<Label htmlFor="schedule-name">Name</Label>
									<Input
										id="schedule-name"
										value={name}
										onChange={(event) => setName(event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="schedule-sevarth">Sevarth ID</Label>
									<Input
										id="schedule-sevarth"
										value={sevarthId}
										onChange={(event) => setSevarthId(event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="schedule-regime">Retirement regime</Label>
									<Select
										value={retirementRegime}
										onValueChange={(value) => {
											setRetirementRegime(value as RetirementRegime);
											setGpfJurisdictionError(null);
											if (value !== "gpf") setGpfJurisdiction("");
										}}
										disabled={isSubmitting}
									>
										<SelectTrigger id="schedule-regime" className="w-full">
											<SelectValue>
												{(value: RetirementRegime | null) =>
													value?.toUpperCase() ?? "Select regime"
												}
											</SelectValue>
										</SelectTrigger>
										<SelectContent>
											<SelectItem value="gpf">GPF</SelectItem>
											<SelectItem value="nps">NPS</SelectItem>
											<SelectItem value="epf">EPF</SelectItem>
										</SelectContent>
									</Select>
								</div>
								{retirementRegime === "gpf" ? (
									<div className="grid gap-2">
										<Label htmlFor="schedule-gpf-jurisdiction">GPF jurisdiction</Label>
										<Select
											value={gpfJurisdiction || null}
											onValueChange={(value) => {
												setGpfJurisdiction(value as GpfJurisdiction);
												setGpfJurisdictionError(null);
											}}
											disabled={isSubmitting}
										>
											<SelectTrigger
												id="schedule-gpf-jurisdiction"
												className="w-full"
												aria-invalid={gpfJurisdictionError ? true : undefined}
											>
												<SelectValue placeholder="Select jurisdiction">
													{(value: GpfJurisdiction | null) =>
														value
															? value.charAt(0).toUpperCase() + value.slice(1)
															: "Select jurisdiction"
													}
												</SelectValue>
											</SelectTrigger>
											<SelectContent>
												<SelectItem value="mumbai">Mumbai</SelectItem>
												<SelectItem value="nagpur">Nagpur</SelectItem>
											</SelectContent>
										</Select>
										{gpfJurisdictionError ? (
											<p className="text-sm text-destructive">{gpfJurisdictionError}</p>
										) : null}
									</div>
								) : null}
								<div className="grid grid-cols-2 gap-3">
									<div className="grid gap-2">
										<Label htmlFor="schedule-dob">Date of birth</Label>
										<Input
											id="schedule-dob"
											type="date"
											value={dateOfBirth}
											onChange={(event) => setDateOfBirth(event.target.value)}
											disabled={isSubmitting}
										/>
									</div>
									<div className="grid gap-2">
										<Label htmlFor="schedule-doj">Date of joining</Label>
										<Input
											id="schedule-doj"
											type="date"
											value={dateOfJoining}
											onChange={(event) => setDateOfJoining(event.target.value)}
											disabled={isSubmitting}
										/>
									</div>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="schedule-pan">PAN</Label>
									<Input
										id="schedule-pan"
										value={pan}
										onChange={(event) => setPan(event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
							</>
						) : null}

						{kind === "posting" ? (
							<>
								<div className="grid gap-2">
									<Label htmlFor="schedule-office">Office ID</Label>
									<Input
										id="schedule-office"
										value={officeId}
										onChange={(event) => setOfficeId(event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="schedule-payroll-unit">Payroll unit ID</Label>
									<Input
										id="schedule-payroll-unit"
										value={payrollUnitId}
										onChange={(event) => setPayrollUnitId(event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="schedule-post">Post ID</Label>
									<Input
										id="schedule-post"
										value={postId}
										onChange={(event) => setPostId(event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
							</>
						) : null}

						{kind === "pay" ? (
							<>
								<div className="grid gap-2">
									<Label htmlFor="schedule-pay-level">Pay matrix level</Label>
									<Input
										id="schedule-pay-level"
										value={payMatrixLevel}
										onChange={(event) => setPayMatrixLevel(event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="schedule-basic-pay">Basic pay</Label>
									<Input
										id="schedule-basic-pay"
										value={basicPay}
										onChange={(event) => setBasicPay(event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
							</>
						) : null}

						{kind === "bank" ? (
							<>
								<div className="grid gap-2">
									<Label htmlFor="schedule-account">Account number</Label>
									<Input
										id="schedule-account"
										value={accountNumber}
										onChange={(event) => setAccountNumber(event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="schedule-ifsc">IFSC</Label>
									<Input
										id="schedule-ifsc"
										value={ifsc}
										onChange={(event) => setIfsc(event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="schedule-bank-name">Bank name</Label>
									<Input
										id="schedule-bank-name"
										value={bankName}
										onChange={(event) => setBankName(event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="schedule-branch">Branch</Label>
									<Input
										id="schedule-branch"
										value={branch}
										onChange={(event) => setBranch(event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
							</>
						) : null}

						<div className="grid gap-2">
							<Label htmlFor="schedule-change-reason">Change reason</Label>
							<Textarea
								id="schedule-change-reason"
								value={changeReason}
								onChange={(event) => setChangeReason(event.target.value)}
								disabled={isSubmitting}
								rows={2}
							/>
						</div>

						{overlapError ? (
							<p className="text-sm text-destructive" role="alert">
								{overlapError}
							</p>
						) : null}
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
							{isSubmitting ? "Saving…" : "Schedule change"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
