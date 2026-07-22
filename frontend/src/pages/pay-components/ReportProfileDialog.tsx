import { type FormEvent, useEffect, useState } from "react";
import { toast } from "sonner";

import { DataEntryField } from "@/components/data-entry/DataEntryField";
import { DataEntryFieldGrid } from "@/components/data-entry/DataEntryFieldGrid";
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
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import {
	type PayrollExportProfile,
	usePayrollExportProfile,
	useUpdatePayrollExportProfile,
} from "@/lib/api/pay-setup";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { getErrorMessage } from "@/lib/errors";

type Form = {
	legal_name: string;
	office_name: string;
	address_lines: string;
	cin: string;
	phone: string;
	website: string;
	ddo_name: string;
	ddo_code: string;
	department_code: string;
	administrative_department: string;
	treasury_code: string;
	fund_source: string;
	plan_status: string;
	demand_number: string;
	major_head: string;
	sub_head: string;
	detailed_head: string;
	salary_reference_prefix: string;
	pay_bill_footer_text: string;
	nps_employee_account_head: string;
	nps_employer_account_head: string;
	mumbai_gpf_office_name: string;
	mumbai_gpf_address: string;
	mumbai_gpf_account_code: string;
	mumbai_gpf_authority_text: string;
	nagpur_gpf_office_name: string;
	nagpur_gpf_address: string;
	nagpur_gpf_account_code: string;
	nagpur_gpf_authority_text: string;
	bank_name: string;
	bank_branch: string;
	bank_address: string;
	maker_name: string;
	maker_designation: string;
	checker_name: string;
	checker_designation: string;
	approver_name: string;
	approver_designation: string;
	final_approver_name: string;
	final_approver_designation: string;
};

type ProfileField = {
	key: keyof Form;
	label: string;
	multiline?: boolean;
	wide?: boolean;
};

type ProfileSection = {
	title: string;
	description: string;
	fields: readonly ProfileField[];
};

const PROFILE_SECTIONS: readonly ProfileSection[] = [
	{
		title: "Organization identity",
		description: "Names and administrative codes printed on formal payroll reports.",
		fields: [
			{ key: "legal_name", label: "Legal name" },
			{ key: "office_name", label: "Office name" },
			{ key: "address_lines", label: "Office address", multiline: true, wide: true },
			{ key: "cin", label: "CIN" },
			{ key: "phone", label: "Phone" },
			{ key: "website", label: "Website" },
			{ key: "ddo_name", label: "DDO name" },
			{ key: "ddo_code", label: "DDO code" },
			{ key: "department_code", label: "Department code" },
			{ key: "administrative_department", label: "Administrative department", wide: true },
		],
	},
	{
		title: "Treasury and head of account",
		description: "Treasury classification used on the bill face and approval note.",
		fields: [
			{ key: "treasury_code", label: "Treasury code" },
			{ key: "fund_source", label: "Fund source" },
			{ key: "plan_status", label: "Plan status" },
			{ key: "demand_number", label: "Demand No." },
			{ key: "major_head", label: "Major head" },
			{ key: "sub_head", label: "Sub head" },
			{ key: "detailed_head", label: "Detailed head" },
			{ key: "salary_reference_prefix", label: "Salary reference prefix", wide: true },
			{
				key: "pay_bill_footer_text",
				label: "Pay Bill footer text",
				multiline: true,
				wide: true,
			},
		],
	},
	{
		title: "NPS remittance",
		description: "Employee and employer account-head narratives printed on NPS schedules.",
		fields: [
			{
				key: "nps_employee_account_head",
				label: "Employee contribution account head",
				multiline: true,
				wide: true,
			},
			{
				key: "nps_employer_account_head",
				label: "Employer contribution account head",
				multiline: true,
				wide: true,
			},
		],
	},
	{
		title: "Bank advice recipient",
		description: "Recipient details used for RTGS and bank advice exports.",
		fields: [
			{ key: "bank_name", label: "Bank name" },
			{ key: "bank_branch", label: "Bank branch" },
			{ key: "bank_address", label: "Bank address", multiline: true, wide: true },
		],
	},
	{
		title: "Mumbai GPF remittance",
		description: "Destination details printed on Mumbai-jurisdiction GPF schedules.",
		fields: [
			{ key: "mumbai_gpf_office_name", label: "Office name" },
			{ key: "mumbai_gpf_account_code", label: "Account code" },
			{ key: "mumbai_gpf_address", label: "Address", multiline: true, wide: true },
			{ key: "mumbai_gpf_authority_text", label: "Authority text", multiline: true, wide: true },
		],
	},
	{
		title: "Nagpur GPF remittance",
		description: "Destination details printed on Nagpur-jurisdiction GPF schedules.",
		fields: [
			{ key: "nagpur_gpf_office_name", label: "Office name" },
			{ key: "nagpur_gpf_account_code", label: "Account code" },
			{ key: "nagpur_gpf_address", label: "Address", multiline: true, wide: true },
			{ key: "nagpur_gpf_authority_text", label: "Authority text", multiline: true, wide: true },
		],
	},
	{
		title: "Report signatories",
		description: "Officers printed in the maker, checker, and approval blocks.",
		fields: [
			{ key: "maker_name", label: "Maker name" },
			{ key: "maker_designation", label: "Maker designation" },
			{ key: "checker_name", label: "Checker name" },
			{ key: "checker_designation", label: "Checker designation" },
			{ key: "approver_name", label: "Approving officer name" },
			{ key: "approver_designation", label: "Approving officer designation" },
			{ key: "final_approver_name", label: "Final approver name" },
			{ key: "final_approver_designation", label: "Final approver designation" },
		],
	},
] as const;

const emptyForm = (): Form => ({
	legal_name: "",
	office_name: "",
	address_lines: "",
	cin: "",
	phone: "",
	website: "",
	ddo_name: "",
	ddo_code: "",
	department_code: "",
	administrative_department: "",
	treasury_code: "",
	fund_source: "",
	plan_status: "",
	demand_number: "",
	major_head: "",
	sub_head: "",
	detailed_head: "",
	salary_reference_prefix: "",
	pay_bill_footer_text: "",
	nps_employee_account_head: "",
	nps_employer_account_head: "",
	mumbai_gpf_office_name: "",
	mumbai_gpf_address: "",
	mumbai_gpf_account_code: "",
	mumbai_gpf_authority_text: "",
	nagpur_gpf_office_name: "",
	nagpur_gpf_address: "",
	nagpur_gpf_account_code: "",
	nagpur_gpf_authority_text: "",
	bank_name: "",
	bank_branch: "",
	bank_address: "",
	maker_name: "",
	maker_designation: "",
	checker_name: "",
	checker_designation: "",
	approver_name: "",
	approver_designation: "",
	final_approver_name: "",
	final_approver_designation: "",
});

function fromProfile(profile: PayrollExportProfile): Form {
	const signatories = profile.signatories ?? [];
	const byRole = new Map(signatories.map((item) => [item.role, item]));
	const maker = byRole.get("maker");
	const checker = byRole.get("checker");
	const approver = byRole.get("approving_officer");
	const finalApprover = byRole.get("final_approver");
	const mumbaiGpf = profile.gpf_remittance_profiles?.mumbai;
	const nagpurGpf = profile.gpf_remittance_profiles?.nagpur;
	return {
		...emptyForm(),
		legal_name: profile.legal_name ?? "",
		office_name: profile.office_name ?? "",
		address_lines: (profile.address_lines ?? []).join("\n"),
		cin: profile.cin ?? "",
		phone: profile.phone ?? "",
		website: profile.website ?? "",
		ddo_name: profile.ddo_name ?? "",
		ddo_code: profile.ddo_code ?? "",
		department_code: profile.department_code ?? "",
		administrative_department: profile.administrative_department ?? "",
		treasury_code: profile.treasury_code ?? "",
		fund_source: profile.fund_source ?? "",
		plan_status: profile.plan_status ?? "",
		demand_number: profile.head_of_account?.demand_number ?? "",
		major_head: profile.head_of_account?.major_head ?? "",
		sub_head: profile.head_of_account?.sub_head ?? "",
		detailed_head: profile.head_of_account?.detailed_head ?? "",
		salary_reference_prefix: profile.salary_reference_prefix ?? "",
		pay_bill_footer_text: profile.pay_bill_footer_text ?? "",
		nps_employee_account_head: profile.nps_employee_account_head ?? "",
		nps_employer_account_head: profile.nps_employer_account_head ?? "",
		mumbai_gpf_office_name: mumbaiGpf?.office_name ?? "",
		mumbai_gpf_address: (mumbaiGpf?.address_lines ?? []).join("\n"),
		mumbai_gpf_account_code: mumbaiGpf?.account_code ?? "",
		mumbai_gpf_authority_text: mumbaiGpf?.authority_text ?? "",
		nagpur_gpf_office_name: nagpurGpf?.office_name ?? "",
		nagpur_gpf_address: (nagpurGpf?.address_lines ?? []).join("\n"),
		nagpur_gpf_account_code: nagpurGpf?.account_code ?? "",
		nagpur_gpf_authority_text: nagpurGpf?.authority_text ?? "",
		bank_name: profile.bank_advice_recipient?.bank_name ?? "",
		bank_branch: profile.bank_advice_recipient?.branch ?? "",
		bank_address: (profile.bank_advice_recipient?.address_lines ?? []).join("\n"),
		maker_name: maker?.name ?? "",
		maker_designation: maker?.designation ?? "",
		checker_name: checker?.name ?? "",
		checker_designation: checker?.designation ?? "",
		approver_name: approver?.name ?? "",
		approver_designation: approver?.designation ?? "",
		final_approver_name: finalApprover?.name ?? "",
		final_approver_designation: finalApprover?.designation ?? "",
	};
}

function optional(value: string): string | null {
	return value.trim() || null;
}

function lines(value: string): string[] {
	return value
		.split(/\r?\n/)
		.map((item) => item.trim())
		.filter(Boolean);
}

function gpfRemittanceProfiles(form: Form): PayrollExportProfile["gpf_remittance_profiles"] {
	const entries = {
		mumbai: {
			office_name: optional(form.mumbai_gpf_office_name),
			address_lines: lines(form.mumbai_gpf_address),
			account_code: optional(form.mumbai_gpf_account_code),
			authority_text: optional(form.mumbai_gpf_authority_text),
		},
		nagpur: {
			office_name: optional(form.nagpur_gpf_office_name),
			address_lines: lines(form.nagpur_gpf_address),
			account_code: optional(form.nagpur_gpf_account_code),
			authority_text: optional(form.nagpur_gpf_authority_text),
		},
	};
	return Object.fromEntries(
		Object.entries(entries).filter(([, value]) =>
			Boolean(
				value.office_name ||
					value.address_lines.length ||
					value.account_code ||
					value.authority_text,
			),
		),
	) as PayrollExportProfile["gpf_remittance_profiles"];
}

export function ReportProfileDialog({
	open,
	onOpenChange,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
}) {
	const profileQuery = usePayrollExportProfile();
	const update = useUpdatePayrollExportProfile();
	const [form, setForm] = useState<Form>(emptyForm);
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (open && profileQuery.data) {
			setForm(fromProfile(profileQuery.data.value));
			setFormError(null);
		}
	}, [open, profileQuery.data]);

	const set = (key: keyof Form, value: string) => {
		setForm((current) => ({ ...current, [key]: value }));
		setFormError(null);
	};
	const save = async () => {
		const signatoryEntries = [
			{ role: "maker", label: "Maker", name: form.maker_name, designation: form.maker_designation },
			{
				role: "checker",
				label: "Checker",
				name: form.checker_name,
				designation: form.checker_designation,
			},
			{
				role: "approving_officer",
				label: "Approving officer",
				name: form.approver_name,
				designation: form.approver_designation,
			},
			{
				role: "final_approver",
				label: "Final approver",
				name: form.final_approver_name,
				designation: form.final_approver_designation,
			},
		] satisfies Array<{
			role: NonNullable<PayrollExportProfile["signatories"]>[number]["role"];
			label: string;
			name: string;
			designation: string;
		}>;
		const incomplete = signatoryEntries.find(
			(entry) => Boolean(entry.name.trim()) !== Boolean(entry.designation.trim()),
		);
		if (incomplete) {
			setFormError(`${incomplete.label} name and designation must be entered together.`);
			return;
		}
		const signatories = signatoryEntries
			.filter((entry) => entry.name.trim())
			.map(({ role, name, designation }) => ({
				role,
				name: name.trim(),
				designation: designation.trim(),
			}));
		const value: PayrollExportProfile = {
			...profileQuery.data?.value,
			legal_name: optional(form.legal_name),
			office_name: optional(form.office_name),
			address_lines: lines(form.address_lines),
			cin: optional(form.cin),
			phone: optional(form.phone),
			website: optional(form.website),
			ddo_name: optional(form.ddo_name),
			ddo_code: optional(form.ddo_code),
			department_code: optional(form.department_code),
			administrative_department: optional(form.administrative_department),
			treasury_code: optional(form.treasury_code),
			fund_source: optional(form.fund_source),
			plan_status: optional(form.plan_status),
			salary_reference_prefix: optional(form.salary_reference_prefix),
			pay_bill_footer_text: optional(form.pay_bill_footer_text),
			nps_employee_account_head: optional(form.nps_employee_account_head),
			nps_employer_account_head: optional(form.nps_employer_account_head),
			head_of_account: {
				demand_number: optional(form.demand_number),
				major_head: optional(form.major_head),
				sub_head: optional(form.sub_head),
				detailed_head: optional(form.detailed_head),
			},
			bank_advice_recipient: {
				bank_name: optional(form.bank_name),
				branch: optional(form.bank_branch),
				address_lines: lines(form.bank_address),
			},
			gpf_remittance_profiles: gpfRemittanceProfiles(form),
			signatories,
		};
		try {
			await update.mutateAsync(value);
			toast.success("Report defaults saved");
			onOpenChange(false);
		} catch (error) {
			setFormError(getErrorMessage(error, "Failed to save report defaults."));
			toast.error(getErrorMessage(error, "Failed to save report defaults."));
		}
	};
	const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		void save();
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.wideForm}>
				<DialogHeader className="gap-1 border-b px-6 py-5 pr-14">
					<DialogTitle>Report Defaults</DialogTitle>
					<DialogDescription>
						Organization details copied into each report snapshot at calculation.
					</DialogDescription>
				</DialogHeader>
				<form className="flex min-h-0 flex-1 flex-col" onSubmit={handleSubmit}>
					<DialogBody className="flex flex-col gap-7 py-6">
						{PROFILE_SECTIONS.map((section, sectionIndex) => (
							<div className="flex flex-col gap-7" key={section.title}>
								{sectionIndex > 0 ? <Separator /> : null}
								<section className="grid gap-5 lg:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] lg:gap-8">
									<div className="flex flex-col gap-1.5">
										<h3 className="text-base font-semibold">{section.title}</h3>
										<p className="text-sm leading-relaxed text-muted-foreground">
											{section.description}
										</p>
									</div>
									<DataEntryFieldGrid columns={2}>
										{section.fields.map((field) => (
											<DataEntryField
												key={field.key}
												label={field.label}
												htmlFor={`report-profile-${field.key}`}
												className={field.wide ? "sm:col-span-2" : undefined}
											>
												{field.multiline ? (
													<Textarea
														id={`report-profile-${field.key}`}
														value={form[field.key]}
														onChange={(event) => set(field.key, event.target.value)}
														placeholder={
															field.key.includes("address") ? "One address line per row" : undefined
														}
														className="min-h-20 resize-y"
														disabled={profileQuery.isLoading || update.isPending}
													/>
												) : (
													<Input
														id={`report-profile-${field.key}`}
														value={form[field.key]}
														onChange={(event) => set(field.key, event.target.value)}
														disabled={profileQuery.isLoading || update.isPending}
													/>
												)}
											</DataEntryField>
										))}
									</DataEntryFieldGrid>
								</section>
							</div>
						))}
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
							disabled={update.isPending}
						>
							Cancel
						</Button>
						<Button type="submit" disabled={profileQuery.isLoading || update.isPending}>
							{update.isPending ? "Saving…" : "Save"}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
