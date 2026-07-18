import { type FormEvent, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { DatePicker, HISTORICAL_DATE_CALENDAR_PROPS } from "@/components/ui/date-picker";
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
	parseApiDate,
	type RetirementRegime,
	toApiDate,
	todayApiDate,
	useCreateEmployeeVersion,
} from "@/lib/api/employees";
import {
	useEmployeeGroupsList,
	useOfficesList,
	usePayrollUnitsList,
	usePostsList,
} from "@/lib/api/org-structure";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { namedEntityLabel, postEntityLabel } from "@/lib/entity-labels";
import { ApiError } from "@/lib/errors";

const NONE_VALUE = "__none__";

function labelForId(
	id: string | null | undefined,
	labels: Record<string, string>,
	fallback = "Select…",
): string {
	if (!id) return fallback;
	return labels[id] ?? fallback;
}

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
	const officesQuery = useOfficesList();
	const payrollUnitsQuery = usePayrollUnitsList();
	const postsQuery = usePostsList();
	const employeeGroupsQuery = useEmployeeGroupsList();

	const offices = officesQuery.data ?? [];
	const payrollUnits = payrollUnitsQuery.data ?? [];
	const posts = postsQuery.data ?? [];
	const employeeGroups = employeeGroupsQuery.data ?? [];

	const officeLabels = useMemo(
		() => Object.fromEntries(offices.map((item) => [item.id, namedEntityLabel(item)])),
		[offices],
	);
	const payrollUnitLabels = useMemo(
		() => Object.fromEntries(payrollUnits.map((item) => [item.id, namedEntityLabel(item)])),
		[payrollUnits],
	);
	const postLabels = useMemo(
		() => Object.fromEntries(posts.map((item) => [item.id, postEntityLabel(item)])),
		[posts],
	);
	const employeeGroupLabels = useMemo(
		() => Object.fromEntries(employeeGroups.map((item) => [item.id, namedEntityLabel(item)])),
		[employeeGroups],
	);

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
		setOverlapError(null);
		setFormError(null);
		setGpfJurisdictionError(null);

		if (kind === "profile" && activeProfile) {
			setName(activeProfile.name);
			setSevarthId(activeProfile.sevarth_id ?? "");
			setRetirementRegime((activeProfile.retirement_regime as RetirementRegime) || "nps");
			setGpfJurisdiction((activeProfile.gpf_jurisdiction as GpfJurisdiction) || "");
			setPan(activeProfile.pan ?? "");
			setPran(activeProfile.pran ?? "");
			setGpfAccountNumber(activeProfile.gpf_account_number ?? "");
			setEpfNumber(activeProfile.epf_number ?? "");
			setDateOfBirth(activeProfile.date_of_birth ?? "");
			setDateOfJoining(activeProfile.date_of_joining ?? "");
		}
		if (kind === "posting" && activePosting) {
			setOfficeId(activePosting.office_id);
			setPayrollUnitId(activePosting.payroll_unit_id);
			setPostId(activePosting.post_id);
			setEmployeeGroupId(activePosting.employee_group_id ?? "");
		}
		if (kind === "pay" && activePay) {
			setPayMatrixLevel(activePay.pay_matrix_level ?? "");
			setBasicPay(activePay.basic_pay);
		}
		if (kind === "bank" && activeBank) {
			setAccountNumber(activeBank.account_number);
			setIfsc(activeBank.ifsc);
			setBankName(activeBank.bank_name);
			setBranch(activeBank.branch ?? "");
		}
	}, [open, kind, activeProfile, activePosting, activePay, activeBank]);

	const postingCatalogLoading =
		kind === "posting" &&
		(officesQuery.isLoading ||
			payrollUnitsQuery.isLoading ||
			postsQuery.isLoading ||
			employeeGroupsQuery.isLoading);

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
							<Label htmlFor="schedule-effective-from">Effective From</Label>
							<DatePicker
								id="schedule-effective-from"
								value={effectiveFrom ? parseApiDate(effectiveFrom) : undefined}
								onValueChange={(date) => setEffectiveFrom(date ? toApiDate(date) : "")}
								disabled={isSubmitting}
								className="w-full"
								placeholder="Effective From"
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
									<Label htmlFor="schedule-regime">Retirement Regime</Label>
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
										<Label htmlFor="schedule-gpf-jurisdiction">GPF Jurisdiction</Label>
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
										<Label htmlFor="schedule-dob">Date of Birth</Label>
										<DatePicker
											id="schedule-dob"
											value={dateOfBirth ? parseApiDate(dateOfBirth) : undefined}
											onValueChange={(date) => setDateOfBirth(date ? toApiDate(date) : "")}
											disabled={isSubmitting}
											className="w-full"
											placeholder="Date of Birth"
											calendarProps={HISTORICAL_DATE_CALENDAR_PROPS}
										/>
									</div>
									<div className="grid gap-2">
										<Label htmlFor="schedule-doj">Date of Joining</Label>
										<DatePicker
											id="schedule-doj"
											value={dateOfJoining ? parseApiDate(dateOfJoining) : undefined}
											onValueChange={(date) => setDateOfJoining(date ? toApiDate(date) : "")}
											disabled={isSubmitting}
											className="w-full"
											placeholder="Date of Joining"
											calendarProps={HISTORICAL_DATE_CALENDAR_PROPS}
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
									<Label htmlFor="schedule-office">Office</Label>
									<Select
										value={officeId || null}
										onValueChange={(value) => setOfficeId(value ?? "")}
										disabled={isSubmitting || postingCatalogLoading}
									>
										<SelectTrigger id="schedule-office" className="w-full">
											<SelectValue placeholder="Select office">
												{(value: string | null) => labelForId(value, officeLabels, "Select office")}
											</SelectValue>
										</SelectTrigger>
										<SelectContent>
											{offices.map((office) => (
												<SelectItem key={office.id} value={office.id}>
													{namedEntityLabel(office)}
												</SelectItem>
											))}
										</SelectContent>
									</Select>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="schedule-payroll-unit">Payroll Unit</Label>
									<Select
										value={payrollUnitId || null}
										onValueChange={(value) => setPayrollUnitId(value ?? "")}
										disabled={isSubmitting || postingCatalogLoading}
									>
										<SelectTrigger id="schedule-payroll-unit" className="w-full">
											<SelectValue placeholder="Select payroll unit">
												{(value: string | null) =>
													labelForId(value, payrollUnitLabels, "Select payroll unit")
												}
											</SelectValue>
										</SelectTrigger>
										<SelectContent>
											{payrollUnits.map((unit) => (
												<SelectItem key={unit.id} value={unit.id}>
													{namedEntityLabel(unit)}
												</SelectItem>
											))}
										</SelectContent>
									</Select>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="schedule-post">Post</Label>
									<Select
										value={postId || null}
										onValueChange={(value) => setPostId(value ?? "")}
										disabled={isSubmitting || postingCatalogLoading}
									>
										<SelectTrigger id="schedule-post" className="w-full">
											<SelectValue placeholder="Select post">
												{(value: string | null) => labelForId(value, postLabels, "Select post")}
											</SelectValue>
										</SelectTrigger>
										<SelectContent>
											{posts.map((post) => (
												<SelectItem key={post.id} value={post.id}>
													{postEntityLabel(post)}
												</SelectItem>
											))}
										</SelectContent>
									</Select>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="schedule-employee-group">Employee Group</Label>
									<Select
										value={employeeGroupId || NONE_VALUE}
										onValueChange={(value) =>
											setEmployeeGroupId(!value || value === NONE_VALUE ? "" : value)
										}
										disabled={isSubmitting || postingCatalogLoading}
									>
										<SelectTrigger id="schedule-employee-group" className="w-full">
											<SelectValue placeholder="None">
												{(value: string | null) =>
													!value || value === NONE_VALUE
														? "None"
														: labelForId(value, employeeGroupLabels, "None")
												}
											</SelectValue>
										</SelectTrigger>
										<SelectContent>
											<SelectItem value={NONE_VALUE}>None</SelectItem>
											{employeeGroups.map((group) => (
												<SelectItem key={group.id} value={group.id}>
													{namedEntityLabel(group)}
												</SelectItem>
											))}
										</SelectContent>
									</Select>
								</div>
							</>
						) : null}

						{kind === "pay" ? (
							<>
								<div className="grid gap-2">
									<Label htmlFor="schedule-pay-level">Pay Matrix Level</Label>
									<Input
										id="schedule-pay-level"
										value={payMatrixLevel}
										onChange={(event) => setPayMatrixLevel(event.target.value)}
										disabled={isSubmitting}
									/>
								</div>
								<div className="grid gap-2">
									<Label htmlFor="schedule-basic-pay">Basic Pay</Label>
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
									<Label htmlFor="schedule-account">Account Number</Label>
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
									<Label htmlFor="schedule-bank-name">Bank Name</Label>
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
							<Label htmlFor="schedule-change-reason">Change Reason</Label>
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
							{isSubmitting ? "Submitting…" : "Submit"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
