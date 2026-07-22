import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { DataEntryField } from "@/components/data-entry/DataEntryField";
import { DataEntryFieldGrid } from "@/components/data-entry/DataEntryFieldGrid";
import { Button } from "@/components/ui/button";
import { DatePicker, HISTORICAL_DATE_CALENDAR_PROPS } from "@/components/ui/date-picker";
import {
	Dialog,
	DialogContent,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
	type CreateEmployeeRequest,
	type GpfJurisdiction,
	type RetirementRegime,
	useCreateEmployee,
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

type CreateEmployeeDialogProps = {
	open: boolean;
	onOpenChange: (open: boolean) => void;
};

type FormState = {
	employee_number: string;
	effective_from: string;
	name: string;
	sevarth_id: string;
	retirement_regime: RetirementRegime;
	gpf_jurisdiction: GpfJurisdiction | "";
	pan: string;
	pran: string;
	pension_account: string;
	gpf_account_number: string;
	epf_number: string;
	date_of_birth: string;
	date_of_joining: string;
	payroll_export_remark: string;
	office_id: string;
	post_id: string;
	pay_bill_post_id: string;
	pay_matrix_level: string;
	basic_pay: string;
	account_number: string;
	ifsc: string;
	bank_name: string;
	branch: string;
};

type CreateEmployeeTab = "details" | "posting" | "pay" | "bank";

const emptyForm = (): FormState => ({
	employee_number: "",
	effective_from: todayApiDate(),
	name: "",
	sevarth_id: "",
	retirement_regime: "nps",
	gpf_jurisdiction: "",
	pan: "",
	pran: "",
	pension_account: "",
	gpf_account_number: "",
	epf_number: "",
	date_of_birth: "",
	date_of_joining: "",
	payroll_export_remark: "",
	office_id: "",
	post_id: "",
	pay_bill_post_id: "",
	pay_matrix_level: "",
	basic_pay: "",
	account_number: "",
	ifsc: "",
	bank_name: "",
	branch: "",
});

function FormSection({ title, children }: { title: string; children: ReactNode }) {
	return (
		<section className="flex flex-col gap-4">
			<h3 className="text-base leading-none font-semibold text-foreground">{title}</h3>
			{children}
		</section>
	);
}

function FormSectionDivider() {
	return <Separator className="my-1" />;
}

export function CreateEmployeeDialog({ open, onOpenChange }: CreateEmployeeDialogProps) {
	const navigate = useNavigate();
	const createEmployee = useCreateEmployee();
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

	const [form, setForm] = useState<FormState>(emptyForm);
	const [activeTab, setActiveTab] = useState<CreateEmployeeTab>("details");
	const [employeeNumberError, setEmployeeNumberError] = useState<string | null>(null);
	const [gpfJurisdictionError, setGpfJurisdictionError] = useState<string | null>(null);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyForm());
			setActiveTab("details");
			setEmployeeNumberError(null);
			setGpfJurisdictionError(null);
			setFormError(null);
		}
	}, [open]);

	const setField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	const postingCatalogLoading = officesQuery.isLoading || postsQuery.isLoading;

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setEmployeeNumberError(null);
		setGpfJurisdictionError(null);
		setFormError(null);

		if (!form.employee_number.trim()) {
			setEmployeeNumberError("Employee number is required");
			setActiveTab("details");
			return;
		}
		if (!form.effective_from) {
			setFormError("Effective from is required.");
			setActiveTab("details");
			return;
		}
		if (!form.name.trim()) {
			setFormError("Name is required.");
			setActiveTab("details");
			return;
		}

		const hasPosting = Boolean(
			form.office_id.trim() || form.post_id.trim() || form.pay_bill_post_id.trim(),
		);
		if (hasPosting && (!form.office_id.trim() || !form.post_id.trim())) {
			setFormError("Select both an office and a post, or leave both blank.");
			setActiveTab("posting");
			return;
		}

		const hasPay = Boolean(form.pay_matrix_level.trim() || form.basic_pay.trim());
		if (hasPay && !form.basic_pay.trim()) {
			setFormError("Basic pay is required when adding pay details.");
			setActiveTab("pay");
			return;
		}

		const hasBank = Boolean(
			form.account_number.trim() || form.ifsc.trim() || form.bank_name.trim() || form.branch.trim(),
		);
		if (hasBank && (!form.account_number.trim() || !form.ifsc.trim() || !form.bank_name.trim())) {
			setFormError("Account number, IFSC, and bank name are required when adding bank details.");
			setActiveTab("bank");
			return;
		}

		const body: CreateEmployeeRequest = {
			employee_number: form.employee_number.trim(),
			effective_from: form.effective_from,
			profile: {
				name: form.name.trim(),
				sevarth_id: form.sevarth_id.trim() || null,
				retirement_regime: form.retirement_regime,
				date_of_birth: form.date_of_birth || null,
				date_of_joining: form.date_of_joining || null,
				payroll_export_remark: form.payroll_export_remark.trim() || null,
				gpf_jurisdiction:
					form.retirement_regime === "gpf" && form.gpf_jurisdiction ? form.gpf_jurisdiction : null,
				pan: form.pan.trim() || null,
				pran: form.pran.trim() || null,
				pension_account: form.pension_account.trim() || null,
				gpf_account_number: form.gpf_account_number.trim() || null,
				epf_number: form.epf_number.trim() || null,
			},
		};

		if (hasPosting) {
			body.posting = {
				office_id: form.office_id.trim(),
				post_id: form.post_id.trim(),
				pay_bill_post_id: form.pay_bill_post_id.trim() || null,
			};
		}

		if (hasPay) {
			body.pay = {
				pay_matrix_level: form.pay_matrix_level.trim() || null,
				basic_pay: form.basic_pay.trim(),
			};
		}

		if (hasBank) {
			body.bank = {
				account_number: form.account_number.trim(),
				ifsc: form.ifsc.trim(),
				bank_name: form.bank_name.trim(),
				branch: form.branch.trim() || null,
				is_primary_salary: true,
			};
		}

		try {
			const created = await createEmployee.mutateAsync(body);
			onOpenChange(false);
			void navigate(`/employees/${created.id}`);
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				setEmployeeNumberError("This employee number is already in use");
				setActiveTab("details");
				return;
			}
			setFormError(error instanceof Error ? error.message : "Unable to create employee.");
			setActiveTab("details");
		}
	};

	const isSubmitting = createEmployee.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.extraWideForm}>
				<DialogHeader className="gap-1 px-6 pt-5 pb-3">
					<DialogTitle className="text-lg leading-tight">New Employee</DialogTitle>
				</DialogHeader>
				<form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
					<Tabs
						value={activeTab}
						className="flex min-h-0 flex-1 flex-col gap-0"
						onValueChange={(value) => setActiveTab(value as CreateEmployeeTab)}
					>
						<div className="scroll-fade-x no-scrollbar w-full shrink-0 overflow-x-auto border-b">
							<TabsList
								variant="line"
								className="h-auto min-h-11 w-max min-w-full flex-nowrap justify-start gap-5 rounded-none border-b-0 bg-transparent px-6 py-0 sm:gap-6"
							>
								<TabsTrigger value="details" className="flex-none px-0 py-3 text-sm">
									Details
								</TabsTrigger>
								<TabsTrigger value="posting" className="flex-none px-0 py-3 text-sm">
									Posting
								</TabsTrigger>
								<TabsTrigger value="pay" className="flex-none px-0 py-3 text-sm">
									Pay
								</TabsTrigger>
								<TabsTrigger value="bank" className="flex-none px-0 py-3 text-sm">
									Bank
								</TabsTrigger>
							</TabsList>
						</div>

						<div className="app-scrollbar min-h-0 min-w-0 flex-1 overflow-y-auto scroll-fade px-6 pt-7 pb-24 sm:pb-8">
							<fieldset disabled={isSubmitting} className="m-0 min-w-0 border-0 p-0">
								<TabsContent value="details" className="mt-0 flex flex-col gap-7">
									<FormSection title="Identity">
										<DataEntryFieldGrid>
											<DataEntryField
												label="Employee Number"
												htmlFor="create-emp-number"
												required
												error={employeeNumberError ?? undefined}
												errorId="create-emp-number-error"
											>
												<Input
													id="create-emp-number"
													value={form.employee_number}
													onChange={(event) => {
														setField("employee_number", event.target.value);
														setEmployeeNumberError(null);
													}}
													aria-invalid={employeeNumberError ? true : undefined}
													aria-describedby={
														employeeNumberError ? "create-emp-number-error" : undefined
													}
												/>
											</DataEntryField>
											<DataEntryField
												label="Effective From"
												htmlFor="create-emp-effective-from"
												required
											>
												<DatePicker
													id="create-emp-effective-from"
													value={
														form.effective_from ? parseApiDate(form.effective_from) : undefined
													}
													onValueChange={(date) =>
														setField("effective_from", date ? toApiDate(date) : "")
													}
													className="w-full"
													placeholder="Effective From"
												/>
											</DataEntryField>
											<DataEntryField label="Name" htmlFor="create-emp-name" required>
												<Input
													id="create-emp-name"
													value={form.name}
													onChange={(event) => setField("name", event.target.value)}
												/>
											</DataEntryField>
											<DataEntryField label="Sevarth ID" htmlFor="create-emp-sevarth">
												<Input
													id="create-emp-sevarth"
													value={form.sevarth_id}
													onChange={(event) => setField("sevarth_id", event.target.value)}
												/>
											</DataEntryField>
											<DataEntryField label="Date of Birth" htmlFor="create-emp-dob">
												<DatePicker
													id="create-emp-dob"
													value={form.date_of_birth ? parseApiDate(form.date_of_birth) : undefined}
													onValueChange={(date) =>
														setField("date_of_birth", date ? toApiDate(date) : "")
													}
													className="w-full"
													placeholder="Date of Birth"
													calendarProps={HISTORICAL_DATE_CALENDAR_PROPS}
												/>
											</DataEntryField>
											<DataEntryField label="Date of Joining" htmlFor="create-emp-doj">
												<DatePicker
													id="create-emp-doj"
													value={
														form.date_of_joining ? parseApiDate(form.date_of_joining) : undefined
													}
													onValueChange={(date) =>
														setField("date_of_joining", date ? toApiDate(date) : "")
													}
													className="w-full"
													placeholder="Date of Joining"
													calendarProps={HISTORICAL_DATE_CALENDAR_PROPS}
												/>
											</DataEntryField>
										</DataEntryFieldGrid>
									</FormSection>

									<FormSectionDivider />

									<FormSection title="Retirement">
										<DataEntryFieldGrid>
											<DataEntryField
												label="Retirement Regime"
												htmlFor="create-emp-regime"
												required
											>
												<Select
													value={form.retirement_regime}
													onValueChange={(value) => {
														setField("retirement_regime", value as RetirementRegime);
														setGpfJurisdictionError(null);
														if (value !== "gpf") {
															setField("gpf_jurisdiction", "");
															setField("gpf_account_number", "");
														}
														if (value !== "nps") {
															setField("pran", "");
															setField("pension_account", "");
														}
														if (value !== "epf") setField("epf_number", "");
													}}
												>
													<SelectTrigger id="create-emp-regime" className="w-full">
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
											</DataEntryField>
											{form.retirement_regime === "gpf" ? (
												<DataEntryField
													label="GPF Jurisdiction"
													htmlFor="create-emp-gpf-jurisdiction"
													error={gpfJurisdictionError ?? undefined}
													errorId="create-emp-gpf-jurisdiction-error"
												>
													<Select
														value={form.gpf_jurisdiction || null}
														onValueChange={(value) => {
															setField("gpf_jurisdiction", value as GpfJurisdiction);
															setGpfJurisdictionError(null);
														}}
													>
														<SelectTrigger
															id="create-emp-gpf-jurisdiction"
															className="w-full"
															aria-invalid={gpfJurisdictionError ? true : undefined}
															aria-describedby={
																gpfJurisdictionError
																	? "create-emp-gpf-jurisdiction-error"
																	: undefined
															}
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
												</DataEntryField>
											) : null}
											{form.retirement_regime === "nps" ? (
												<DataEntryField label="PRAN" htmlFor="create-emp-pran">
													<Input
														id="create-emp-pran"
														value={form.pran}
														onChange={(event) => setField("pran", event.target.value)}
													/>
												</DataEntryField>
											) : null}
											{form.retirement_regime === "nps" ? (
												<DataEntryField
													label="Pension Account"
													htmlFor="create-emp-pension-account"
												>
													<Input
														id="create-emp-pension-account"
														value={form.pension_account}
														onChange={(event) => setField("pension_account", event.target.value)}
													/>
												</DataEntryField>
											) : null}
											{form.retirement_regime === "gpf" ? (
												<DataEntryField label="GPF Account Number" htmlFor="create-emp-gpf-account">
													<Input
														id="create-emp-gpf-account"
														value={form.gpf_account_number}
														onChange={(event) => setField("gpf_account_number", event.target.value)}
													/>
												</DataEntryField>
											) : null}
											{form.retirement_regime === "epf" ? (
												<DataEntryField label="EPF Number" htmlFor="create-emp-epf">
													<Input
														id="create-emp-epf"
														value={form.epf_number}
														onChange={(event) => setField("epf_number", event.target.value)}
													/>
												</DataEntryField>
											) : null}
											<DataEntryField label="PAN" htmlFor="create-emp-pan">
												<Input
													id="create-emp-pan"
													value={form.pan}
													onChange={(event) => setField("pan", event.target.value)}
												/>
											</DataEntryField>
										</DataEntryFieldGrid>
									</FormSection>

									<FormSectionDivider />

									<FormSection title="Pay Bill Export">
										<DataEntryField
											label="Payroll Export Remark"
											htmlFor="create-emp-payroll-export-remark"
										>
											<Textarea
												id="create-emp-payroll-export-remark"
												value={form.payroll_export_remark}
												onChange={(event) => setField("payroll_export_remark", event.target.value)}
												placeholder="Optional employee-specific note printed on canonical Pay Bills"
											/>
										</DataEntryField>
									</FormSection>

									{formError ? (
										<p className="text-sm text-destructive" role="alert">
											{formError}
										</p>
									) : null}
								</TabsContent>

								<TabsContent value="posting" className="mt-0 flex flex-col gap-7">
									<FormSection title="Posting">
										<DataEntryFieldGrid columns={2}>
											<DataEntryField label="Office" htmlFor="create-emp-office">
												<Select
													value={form.office_id || null}
													onValueChange={(value) => setField("office_id", value ?? "")}
													disabled={postingCatalogLoading}
												>
													<SelectTrigger id="create-emp-office" className="w-full">
														<SelectValue placeholder="Select office">
															{(value: string | null) =>
																labelForId(value, officeLabels, "Select office")
															}
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
											</DataEntryField>
											<DataEntryField label="Post" htmlFor="create-emp-post">
												<Select
													value={form.post_id || null}
													onValueChange={(value) => setField("post_id", value ?? "")}
													disabled={postingCatalogLoading}
												>
													<SelectTrigger id="create-emp-post" className="w-full">
														<SelectValue placeholder="Select post">
															{(value: string | null) =>
																labelForId(value, postLabels, "Select post")
															}
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
											</DataEntryField>
										</DataEntryFieldGrid>
										<DataEntryField label="Pay Bill Group" htmlFor="create-emp-pay-bill-post">
											<Select
												value={form.pay_bill_post_id || SAME_AS_DESIGNATION_POST}
												onValueChange={(value) =>
													setField(
														"pay_bill_post_id",
														value === SAME_AS_DESIGNATION_POST ? "" : (value ?? ""),
													)
												}
												disabled={postingCatalogLoading}
											>
												<SelectTrigger id="create-emp-pay-bill-post" className="w-full">
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
										</DataEntryField>
									</FormSection>
									{formError ? (
										<p className="text-sm text-destructive" role="alert">
											{formError}
										</p>
									) : null}
								</TabsContent>

								<TabsContent value="pay" className="mt-0 flex flex-col gap-7">
									<FormSection title="Pay">
										<DataEntryFieldGrid columns={2}>
											<DataEntryField label="Pay Matrix Level" htmlFor="create-emp-pay-level">
												<Input
													id="create-emp-pay-level"
													value={form.pay_matrix_level}
													onChange={(event) => setField("pay_matrix_level", event.target.value)}
												/>
											</DataEntryField>
											<DataEntryField label="Basic Pay" htmlFor="create-emp-basic-pay">
												<Input
													id="create-emp-basic-pay"
													value={form.basic_pay}
													onChange={(event) => setField("basic_pay", event.target.value)}
												/>
											</DataEntryField>
										</DataEntryFieldGrid>
									</FormSection>
									{formError ? (
										<p className="text-sm text-destructive" role="alert">
											{formError}
										</p>
									) : null}
								</TabsContent>

								<TabsContent value="bank" className="mt-0 flex flex-col gap-7">
									<FormSection title="Bank">
										<DataEntryFieldGrid>
											<DataEntryField label="Account Number" htmlFor="create-emp-account">
												<Input
													id="create-emp-account"
													value={form.account_number}
													onChange={(event) => setField("account_number", event.target.value)}
												/>
											</DataEntryField>
											<DataEntryField label="IFSC" htmlFor="create-emp-ifsc">
												<Input
													id="create-emp-ifsc"
													value={form.ifsc}
													onChange={(event) => setField("ifsc", event.target.value)}
												/>
											</DataEntryField>
											<DataEntryField label="Bank Name" htmlFor="create-emp-bank-name">
												<Input
													id="create-emp-bank-name"
													value={form.bank_name}
													onChange={(event) => setField("bank_name", event.target.value)}
												/>
											</DataEntryField>
											<DataEntryField label="Branch" htmlFor="create-emp-branch">
												<Input
													id="create-emp-branch"
													value={form.branch}
													onChange={(event) => setField("branch", event.target.value)}
												/>
											</DataEntryField>
										</DataEntryFieldGrid>
									</FormSection>
									{formError ? (
										<p className="text-sm text-destructive" role="alert">
											{formError}
										</p>
									) : null}
								</TabsContent>
							</fieldset>
						</div>
					</Tabs>

					<DialogFooter className="flex-row gap-2 border-t px-6 py-4">
						<Button
							type="button"
							variant="outline"
							onClick={() => onOpenChange(false)}
							disabled={isSubmitting}
						>
							Cancel
						</Button>
						<Button type="submit" disabled={isSubmitting}>
							{isSubmitting ? "Creating…" : "Create"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
