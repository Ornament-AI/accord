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
	type RetirementRegime,
	useCreateEmployeeVersion,
} from "@/lib/api/employees";
import { useOfficesList, usePostsList } from "@/lib/api/org-structure";
import { parseApiDate, toApiDate, todayApiDate } from "@/lib/calendar-date";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { namedEntityLabel, postEntityLabel } from "@/lib/entity-labels";
import { ApiError } from "@/lib/errors";

const SAME_AS_DESIGNATION_POST = "__same_as_designation_post__";

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
	const postsQuery = usePostsList();

	const offices = officesQuery.data ?? [];
	const posts = postsQuery.data ?? [];

	const officeLabels = useMemo(
		() => Object.fromEntries(offices.map((item) => [item.id, namedEntityLabel(item)])),
		[offices],
	);
	const postLabels = useMemo(
		() => Object.fromEntries(posts.map((item) => [item.id, postEntityLabel(item)])),
		[posts],
	);
	const payBillPostLabels = useMemo(
		() =>
			Object.fromEntries(posts.map((item) => [item.id, item.pay_bill_heading ?? item.designation])),
		[posts],
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
	const [pensionAccount, setPensionAccount] = useState("");
	const [gpfAccountNumber, setGpfAccountNumber] = useState("");
	const [epfNumber, setEpfNumber] = useState("");
	const [dateOfBirth, setDateOfBirth] = useState("");
	const [dateOfJoining, setDateOfJoining] = useState("");
	const [payrollExportRemark, setPayrollExportRemark] = useState("");
	const [gpfJurisdictionError, setGpfJurisdictionError] = useState<string | null>(null);

	// Posting fields
	const [officeId, setOfficeId] = useState("");
	const [postId, setPostId] = useState("");
	const [payBillPostId, setPayBillPostId] = useState("");

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
			setSevarthId(activeProfile.sevarth_id ?? "");
			setRetirementRegime((activeProfile.retirement_regime as RetirementRegime) || "nps");
			setGpfJurisdiction((activeProfile.gpf_jurisdiction as GpfJurisdiction) || "");
			setPan(activeProfile.pan ?? "");
			setPran(activeProfile.pran ?? "");
			setPensionAccount(activeProfile.pension_account ?? "");
			setGpfAccountNumber(activeProfile.gpf_account_number ?? "");
			setEpfNumber(activeProfile.epf_number ?? "");
			setDateOfBirth(activeProfile.date_of_birth ?? "");
			setDateOfJoining(activeProfile.date_of_joining ?? "");
			setPayrollExportRemark(activeProfile.payroll_export_remark ?? "");
		}
		if (kind === "posting") {
			setOfficeId(activePosting?.office_id ?? "");
			setPostId(activePosting?.post_id ?? "");
			setPayBillPostId(activePosting?.pay_bill_post_id ?? "");
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
		kind === "posting" && (officesQuery.isLoading || postsQuery.isLoading);

	const buildBody = (): Record<string, unknown> | null => {
		const base = {
			effective_from: effectiveFrom,
			change_reason: changeReason.trim() || null,
		};

		if (kind === "profile") {
			return {
				...base,
				name: name.trim(),
				sevarth_id: sevarthId.trim() || null,
				retirement_regime: retirementRegime,
				gpf_jurisdiction: retirementRegime === "gpf" ? gpfJurisdiction : null,
				pan: pan.trim() || null,
				pran: pran.trim() || null,
				pension_account: pensionAccount.trim() || null,
				gpf_account_number: gpfAccountNumber.trim() || null,
				epf_number: epfNumber.trim() || null,
				date_of_birth: dateOfBirth.trim() || null,
				date_of_joining: dateOfJoining.trim() || null,
				payroll_export_remark: payrollExportRemark.trim() || null,
			};
		}
		if (kind === "posting") {
			return {
				...base,
				office_id: officeId.trim(),
				post_id: postId.trim(),
				pay_bill_post_id: payBillPostId.trim() || null,
			};
		}
		if (kind === "pay") {
			return {
				...base,
				pay_matrix_level: payMatrixLevel.trim() || null,
				basic_pay: basicPay.trim(),
			};
		}
		return {
			...base,
			account_number: accountNumber.trim(),
			ifsc: ifsc.trim(),
			bank_name: bankName.trim(),
			branch: branch.trim() || null,
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
					<DialogTitle>Schedule {kindLabels[kind]} Change</DialogTitle>
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
											if (value !== "gpf") {
												setGpfJurisdiction("");
												setGpfAccountNumber("");
											}
											if (value !== "nps") {
												setPran("");
												setPensionAccount("");
											}
											if (value !== "epf") setEpfNumber("");
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
								{retirementRegime === "nps" ? (
									<>
										<div className="grid gap-2">
											<Label htmlFor="schedule-pran">PRAN</Label>
											<Input
												id="schedule-pran"
												value={pran}
												onChange={(event) => setPran(event.target.value)}
												disabled={isSubmitting}
											/>
										</div>
										<div className="grid gap-2">
											<Label htmlFor="schedule-pension-account">Pension Account</Label>
											<Input
												id="schedule-pension-account"
												value={pensionAccount}
												onChange={(event) => setPensionAccount(event.target.value)}
												disabled={isSubmitting}
											/>
										</div>
									</>
								) : null}
								{retirementRegime === "gpf" ? (
									<div className="grid gap-2">
										<Label htmlFor="schedule-gpf-account">GPF Account Number</Label>
										<Input
											id="schedule-gpf-account"
											value={gpfAccountNumber}
											onChange={(event) => setGpfAccountNumber(event.target.value)}
											disabled={isSubmitting}
										/>
									</div>
								) : null}
								{retirementRegime === "epf" ? (
									<div className="grid gap-2">
										<Label htmlFor="schedule-epf-account">EPF Number</Label>
										<Input
											id="schedule-epf-account"
											value={epfNumber}
											onChange={(event) => setEpfNumber(event.target.value)}
											disabled={isSubmitting}
										/>
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
								<div className="grid gap-2">
									<Label htmlFor="schedule-payroll-export-remark">Payroll Export Remark</Label>
									<Textarea
										id="schedule-payroll-export-remark"
										value={payrollExportRemark}
										onChange={(event) => setPayrollExportRemark(event.target.value)}
										disabled={isSubmitting}
										rows={2}
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
									<Label htmlFor="schedule-pay-bill-post">Pay Bill Group</Label>
									<Select
										value={payBillPostId || SAME_AS_DESIGNATION_POST}
										onValueChange={(value) =>
											setPayBillPostId(value === SAME_AS_DESIGNATION_POST ? "" : (value ?? ""))
										}
										disabled={isSubmitting || postingCatalogLoading}
									>
										<SelectTrigger id="schedule-pay-bill-post" className="w-full">
											<SelectValue>
												{(value: string | null) =>
													value === SAME_AS_DESIGNATION_POST
														? "Same as designation post"
														: labelForId(value, payBillPostLabels, "Same as designation post")
												}
											</SelectValue>
										</SelectTrigger>
										<SelectContent>
											<SelectItem value={SAME_AS_DESIGNATION_POST}>
												Same as designation post
											</SelectItem>
											{posts.map((post) => (
												<SelectItem key={post.id} value={post.id}>
													{post.pay_bill_heading ?? post.designation}
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
