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

type Form = Record<string, string>;

type ProfileField = {
	key: string;
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
			{ key: "ddo_name", label: "DDO name" },
			{ key: "ddo_code", label: "DDO code" },
			{ key: "department_code", label: "Department code" },
		],
	},
	{
		title: "Treasury and head of account",
		description: "Treasury classification used on the bill face and approval note.",
		fields: [
			{ key: "treasury_code", label: "Treasury code" },
			{ key: "demand_number", label: "Demand No." },
			{ key: "major_head", label: "Major head" },
			{ key: "sub_head", label: "Sub head" },
			{ key: "detailed_head", label: "Detailed head" },
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
		title: "Report signatories",
		description: "Officers printed in the maker, checker, and approval blocks.",
		fields: [
			{ key: "maker_name", label: "Maker name" },
			{ key: "maker_designation", label: "Maker designation" },
			{ key: "checker_name", label: "Checker name" },
			{ key: "checker_designation", label: "Checker designation" },
			{ key: "approver_name", label: "Approving officer name" },
			{ key: "approver_designation", label: "Approving officer designation" },
		],
	},
] as const;

const emptyForm = (): Form => ({
	legal_name: "",
	office_name: "",
	address_lines: "",
	ddo_name: "",
	ddo_code: "",
	department_code: "",
	treasury_code: "",
	demand_number: "",
	major_head: "",
	sub_head: "",
	detailed_head: "",
	bank_name: "",
	bank_branch: "",
	bank_address: "",
	maker_name: "",
	maker_designation: "",
	checker_name: "",
	checker_designation: "",
	approver_name: "",
	approver_designation: "",
});

function fromProfile(profile: PayrollExportProfile): Form {
	const signatories = profile.signatories ?? [];
	const byRole = new Map(signatories.map((item) => [item.role, item]));
	const maker = byRole.get("maker");
	const checker = byRole.get("checker");
	const approver = byRole.get("approving_officer");
	return {
		...emptyForm(),
		legal_name: profile.legal_name ?? "",
		office_name: profile.office_name ?? "",
		address_lines: (profile.address_lines ?? []).join(", "),
		ddo_name: profile.ddo_name ?? "",
		ddo_code: profile.ddo_code ?? "",
		department_code: profile.department_code ?? "",
		treasury_code: profile.treasury_code ?? "",
		demand_number: profile.head_of_account?.demand_number ?? "",
		major_head: profile.head_of_account?.major_head ?? "",
		sub_head: profile.head_of_account?.sub_head ?? "",
		detailed_head: profile.head_of_account?.detailed_head ?? "",
		bank_name: profile.bank_advice_recipient?.bank_name ?? "",
		bank_branch: profile.bank_advice_recipient?.branch ?? "",
		bank_address: (profile.bank_advice_recipient?.address_lines ?? []).join(", "),
		maker_name: maker?.name ?? "",
		maker_designation: maker?.designation ?? "",
		checker_name: checker?.name ?? "",
		checker_designation: checker?.designation ?? "",
		approver_name: approver?.name ?? "",
		approver_designation: approver?.designation ?? "",
	};
}

function optional(value: string): string | null {
	return value.trim() || null;
}

function lines(value: string): string[] {
	return value
		.split(",")
		.map((item) => item.trim())
		.filter(Boolean);
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

	useEffect(() => {
		if (open && profileQuery.data) setForm(fromProfile(profileQuery.data.value));
	}, [open, profileQuery.data]);

	const set = (key: string, value: string) => setForm((current) => ({ ...current, [key]: value }));
	const save = async () => {
		const signatories = [
			["maker", form.maker_name, form.maker_designation],
			["checker", form.checker_name, form.checker_designation],
			["approving_officer", form.approver_name, form.approver_designation],
		]
			.filter(([, name]) => name.trim())
			.map(([role, name, designation]) => ({
				role,
				name: name.trim(),
				designation: designation.trim(),
			}));
		const value: PayrollExportProfile = {
			...profileQuery.data?.value,
			legal_name: optional(form.legal_name),
			office_name: optional(form.office_name),
			address_lines: lines(form.address_lines),
			ddo_name: optional(form.ddo_name),
			ddo_code: optional(form.ddo_code),
			department_code: optional(form.department_code),
			treasury_code: optional(form.treasury_code),
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
			signatories,
		};
		try {
			await update.mutateAsync(value);
			toast.success("Report defaults saved");
			onOpenChange(false);
		} catch (error) {
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
														placeholder="Separate address lines with commas"
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
