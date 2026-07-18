import { ChevronDown } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
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
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import {
	type CreateEmployeeRequest,
	type GpfJurisdiction,
	type RetirementRegime,
	todayApiDate,
	useCreateEmployee,
} from "@/lib/api/employees";
import { ApiError } from "@/lib/errors";

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
	gpf_account_number: string;
	epf_number: string;
	date_of_birth: string;
	date_of_joining: string;
	office_id: string;
	payroll_unit_id: string;
	post_id: string;
	employee_group_id: string;
	pay_matrix_level: string;
	basic_pay: string;
	account_number: string;
	ifsc: string;
	bank_name: string;
	branch: string;
};

const emptyForm = (): FormState => ({
	employee_number: "",
	effective_from: todayApiDate(),
	name: "",
	sevarth_id: "",
	retirement_regime: "nps",
	gpf_jurisdiction: "",
	pan: "",
	pran: "",
	gpf_account_number: "",
	epf_number: "",
	date_of_birth: "",
	date_of_joining: "",
	office_id: "",
	payroll_unit_id: "",
	post_id: "",
	employee_group_id: "",
	pay_matrix_level: "",
	basic_pay: "",
	account_number: "",
	ifsc: "",
	bank_name: "",
	branch: "",
});

export function CreateEmployeeDialog({ open, onOpenChange }: CreateEmployeeDialogProps) {
	const navigate = useNavigate();
	const createEmployee = useCreateEmployee();
	const [form, setForm] = useState<FormState>(emptyForm);
	const [postingOpen, setPostingOpen] = useState(false);
	const [payOpen, setPayOpen] = useState(false);
	const [bankOpen, setBankOpen] = useState(false);
	const [employeeNumberError, setEmployeeNumberError] = useState<string | null>(null);
	const [gpfJurisdictionError, setGpfJurisdictionError] = useState<string | null>(null);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!open) {
			setForm(emptyForm());
			setPostingOpen(false);
			setPayOpen(false);
			setBankOpen(false);
			setEmployeeNumberError(null);
			setGpfJurisdictionError(null);
			setFormError(null);
		}
	}, [open]);

	const setField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setEmployeeNumberError(null);
		setGpfJurisdictionError(null);
		setFormError(null);

		if (!form.employee_number.trim()) {
			setEmployeeNumberError("Employee number is required");
			return;
		}
		if (!form.name.trim() || !form.sevarth_id.trim()) {
			setFormError("Name and Sevarth ID are required.");
			return;
		}
		if (!form.date_of_birth || !form.date_of_joining) {
			setFormError("Date of birth and date of joining are required.");
			return;
		}
		if (form.retirement_regime === "gpf" && !form.gpf_jurisdiction) {
			setGpfJurisdictionError("GPF jurisdiction is required when regime is GPF");
			return;
		}

		const body: CreateEmployeeRequest = {
			employee_number: form.employee_number.trim(),
			effective_from: form.effective_from,
			profile: {
				name: form.name.trim(),
				sevarth_id: form.sevarth_id.trim(),
				retirement_regime: form.retirement_regime,
				date_of_birth: form.date_of_birth,
				date_of_joining: form.date_of_joining,
				gpf_jurisdiction:
					form.retirement_regime === "gpf" && form.gpf_jurisdiction ? form.gpf_jurisdiction : null,
				pan: form.pan.trim() || null,
				pran: form.pran.trim() || null,
				gpf_account_number: form.gpf_account_number.trim() || null,
				epf_number: form.epf_number.trim() || null,
			},
		};

		if (form.office_id.trim() && form.payroll_unit_id.trim() && form.post_id.trim()) {
			body.posting = {
				office_id: form.office_id.trim(),
				payroll_unit_id: form.payroll_unit_id.trim(),
				post_id: form.post_id.trim(),
				employee_group_id: form.employee_group_id.trim() || null,
			};
		}

		if (form.pay_matrix_level.trim() && form.basic_pay.trim()) {
			body.pay = {
				pay_matrix_level: form.pay_matrix_level.trim(),
				basic_pay: form.basic_pay.trim(),
			};
		}

		if (
			form.account_number.trim() &&
			form.ifsc.trim() &&
			form.bank_name.trim() &&
			form.branch.trim()
		) {
			body.bank = {
				account_number: form.account_number.trim(),
				ifsc: form.ifsc.trim(),
				bank_name: form.bank_name.trim(),
				branch: form.branch.trim(),
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
				return;
			}
			setFormError(error instanceof Error ? error.message : "Unable to create employee.");
		}
	};

	const isSubmitting = createEmployee.isPending;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
				<form onSubmit={handleSubmit} className="grid gap-4">
					<DialogHeader>
						<DialogTitle>New employee</DialogTitle>
						<DialogDescription>
							Create an employee header with an initial profile version.
						</DialogDescription>
					</DialogHeader>

					<div className="grid gap-2">
						<Label htmlFor="create-emp-number">Employee number</Label>
						<Input
							id="create-emp-number"
							value={form.employee_number}
							onChange={(event) => {
								setField("employee_number", event.target.value);
								setEmployeeNumberError(null);
							}}
							disabled={isSubmitting}
							aria-invalid={employeeNumberError ? true : undefined}
						/>
						{employeeNumberError ? (
							<p className="text-sm text-destructive">{employeeNumberError}</p>
						) : null}
					</div>

					<div className="grid gap-2">
						<Label htmlFor="create-emp-effective-from">Effective from</Label>
						<Input
							id="create-emp-effective-from"
							type="date"
							value={form.effective_from}
							onChange={(event) => setField("effective_from", event.target.value)}
							disabled={isSubmitting}
						/>
					</div>

					<div className="grid gap-2">
						<Label htmlFor="create-emp-name">Name</Label>
						<Input
							id="create-emp-name"
							value={form.name}
							onChange={(event) => setField("name", event.target.value)}
							disabled={isSubmitting}
						/>
					</div>

					<div className="grid gap-2">
						<Label htmlFor="create-emp-sevarth">Sevarth ID</Label>
						<Input
							id="create-emp-sevarth"
							value={form.sevarth_id}
							onChange={(event) => setField("sevarth_id", event.target.value)}
							disabled={isSubmitting}
						/>
					</div>

					<div className="grid gap-2">
						<Label htmlFor="create-emp-regime">Retirement regime</Label>
						<Select
							value={form.retirement_regime}
							onValueChange={(value) => {
								setField("retirement_regime", value as RetirementRegime);
								setGpfJurisdictionError(null);
								if (value !== "gpf") {
									setField("gpf_jurisdiction", "");
								}
							}}
							disabled={isSubmitting}
						>
							<SelectTrigger id="create-emp-regime" className="w-full">
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								<SelectItem value="gpf">GPF</SelectItem>
								<SelectItem value="nps">NPS</SelectItem>
								<SelectItem value="epf">EPF</SelectItem>
							</SelectContent>
						</Select>
					</div>

					{form.retirement_regime === "gpf" ? (
						<div className="grid gap-2">
							<Label htmlFor="create-emp-gpf-jurisdiction">GPF jurisdiction</Label>
							<Select
								value={form.gpf_jurisdiction || undefined}
								onValueChange={(value) => {
									setField("gpf_jurisdiction", value as GpfJurisdiction);
									setGpfJurisdictionError(null);
								}}
								disabled={isSubmitting}
							>
								<SelectTrigger
									id="create-emp-gpf-jurisdiction"
									className="w-full"
									aria-invalid={gpfJurisdictionError ? true : undefined}
								>
									<SelectValue placeholder="Select jurisdiction" />
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
							<Label htmlFor="create-emp-dob">Date of birth</Label>
							<Input
								id="create-emp-dob"
								type="date"
								value={form.date_of_birth}
								onChange={(event) => setField("date_of_birth", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>
						<div className="grid gap-2">
							<Label htmlFor="create-emp-doj">Date of joining</Label>
							<Input
								id="create-emp-doj"
								type="date"
								value={form.date_of_joining}
								onChange={(event) => setField("date_of_joining", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>
					</div>

					<div className="grid gap-2">
						<Label htmlFor="create-emp-pan">PAN</Label>
						<Input
							id="create-emp-pan"
							value={form.pan}
							onChange={(event) => setField("pan", event.target.value)}
							disabled={isSubmitting}
						/>
					</div>

					{form.retirement_regime === "nps" || form.retirement_regime === "gpf" ? (
						<div className="grid gap-2">
							<Label htmlFor="create-emp-pran">PRAN</Label>
							<Input
								id="create-emp-pran"
								value={form.pran}
								onChange={(event) => setField("pran", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>
					) : null}

					{form.retirement_regime === "gpf" ? (
						<div className="grid gap-2">
							<Label htmlFor="create-emp-gpf-account">GPF account number</Label>
							<Input
								id="create-emp-gpf-account"
								value={form.gpf_account_number}
								onChange={(event) => setField("gpf_account_number", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>
					) : null}

					{form.retirement_regime === "epf" ? (
						<div className="grid gap-2">
							<Label htmlFor="create-emp-epf">EPF number</Label>
							<Input
								id="create-emp-epf"
								value={form.epf_number}
								onChange={(event) => setField("epf_number", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>
					) : null}

					<OptionalSection title="Posting" open={postingOpen} onOpenChange={setPostingOpen}>
						<div className="grid gap-2">
							<Label htmlFor="create-emp-office">Office ID</Label>
							<Input
								id="create-emp-office"
								value={form.office_id}
								onChange={(event) => setField("office_id", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>
						<div className="grid gap-2">
							<Label htmlFor="create-emp-payroll-unit">Payroll unit ID</Label>
							<Input
								id="create-emp-payroll-unit"
								value={form.payroll_unit_id}
								onChange={(event) => setField("payroll_unit_id", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>
						<div className="grid gap-2">
							<Label htmlFor="create-emp-post">Post ID</Label>
							<Input
								id="create-emp-post"
								value={form.post_id}
								onChange={(event) => setField("post_id", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>
					</OptionalSection>

					<OptionalSection title="Pay" open={payOpen} onOpenChange={setPayOpen}>
						<div className="grid gap-2">
							<Label htmlFor="create-emp-pay-level">Pay matrix level</Label>
							<Input
								id="create-emp-pay-level"
								value={form.pay_matrix_level}
								onChange={(event) => setField("pay_matrix_level", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>
						<div className="grid gap-2">
							<Label htmlFor="create-emp-basic-pay">Basic pay</Label>
							<Input
								id="create-emp-basic-pay"
								value={form.basic_pay}
								onChange={(event) => setField("basic_pay", event.target.value)}
								placeholder="50732.00"
								disabled={isSubmitting}
							/>
						</div>
					</OptionalSection>

					<OptionalSection title="Bank" open={bankOpen} onOpenChange={setBankOpen}>
						<div className="grid gap-2">
							<Label htmlFor="create-emp-account">Account number</Label>
							<Input
								id="create-emp-account"
								value={form.account_number}
								onChange={(event) => setField("account_number", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>
						<div className="grid gap-2">
							<Label htmlFor="create-emp-ifsc">IFSC</Label>
							<Input
								id="create-emp-ifsc"
								value={form.ifsc}
								onChange={(event) => setField("ifsc", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>
						<div className="grid gap-2">
							<Label htmlFor="create-emp-bank-name">Bank name</Label>
							<Input
								id="create-emp-bank-name"
								value={form.bank_name}
								onChange={(event) => setField("bank_name", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>
						<div className="grid gap-2">
							<Label htmlFor="create-emp-branch">Branch</Label>
							<Input
								id="create-emp-branch"
								value={form.branch}
								onChange={(event) => setField("branch", event.target.value)}
								disabled={isSubmitting}
							/>
						</div>
					</OptionalSection>

					{formError ? <p className="text-sm text-destructive">{formError}</p> : null}

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
							{isSubmitting ? "Creating…" : "Create employee"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

function OptionalSection({
	title,
	open,
	onOpenChange,
	children,
}: {
	title: string;
	open: boolean;
	onOpenChange: (open: boolean) => void;
	children: React.ReactNode;
}) {
	return (
		<Collapsible open={open} onOpenChange={onOpenChange}>
			<CollapsibleTrigger
				render={
					<Button type="button" variant="ghost" className="h-8 w-full justify-between px-2" />
				}
			>
				<span>{title}</span>
				<ChevronDown className="size-4 opacity-60" />
			</CollapsibleTrigger>
			<CollapsibleContent className="grid gap-3 pt-2">{children}</CollapsibleContent>
		</Collapsible>
	);
}
