import { useEffect, useState } from "react";
import { toast } from "sonner";

import { PageSection } from "@/components/page-shell";
import { Button } from "@/components/ui/button";
import { DatePicker, SCHEDULABLE_DATE_CALENDAR_PROPS } from "@/components/ui/date-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	type PayrollRunReportMetadata,
	useUpdatePayrollRunReportMetadata,
} from "@/lib/api/payroll-runs";
import { parseApiDate, toApiDate } from "@/lib/calendar-date";
import { getErrorMessage } from "@/lib/errors";

const FIELDS: ReadonlyArray<{
	key: keyof PayrollRunReportMetadata;
	label: string;
	kind?: "date";
	required?: boolean;
}> = [
	{ key: "bill_number", label: "Bill No.", required: true },
	{ key: "bill_date", label: "Bill date", kind: "date", required: true },
	{ key: "payment_date", label: "Payment date", kind: "date" },
	{ key: "demand_number", label: "Demand No.", required: true },
	{ key: "major_head", label: "Major head", required: true },
	{ key: "sub_head", label: "Sub head", required: true },
	{ key: "detailed_head", label: "Detailed head", required: true },
	{ key: "bank_advice_number", label: "Bank advice No." },
	{ key: "bank_advice_date", label: "Bank advice date", kind: "date" },
	{ key: "approval_note_number", label: "Approval note No." },
	{ key: "approval_note_date", label: "Approval note date", kind: "date" },
];

function normalized(metadata: PayrollRunReportMetadata): PayrollRunReportMetadata {
	return Object.fromEntries(
		FIELDS.map(({ key }) => [key, metadata[key] ?? null]),
	) as PayrollRunReportMetadata;
}

export function ReportMetadataSection({
	runId,
	metadata,
	editable,
}: {
	runId: string;
	metadata: PayrollRunReportMetadata;
	editable: boolean;
}) {
	const [form, setForm] = useState<PayrollRunReportMetadata>(() => normalized(metadata));
	const update = useUpdatePayrollRunReportMetadata(runId);

	useEffect(() => setForm(normalized(metadata)), [metadata]);
	const setField = (key: keyof PayrollRunReportMetadata, value: string | null) =>
		setForm((current) => ({ ...current, [key]: value }));

	const save = async () => {
		try {
			await update.mutateAsync(form);
			toast.success("Report details saved");
		} catch (error) {
			toast.error(getErrorMessage(error, "Failed to save report details."));
		}
	};

	return (
		<PageSection className="grid gap-4">
			<div className="flex items-center justify-between gap-3">
				<div>
					<h2 className="text-base font-semibold">Report Details</h2>
					<p className="text-sm text-muted-foreground">
						These values are frozen into the report snapshot when the run is posted.
					</p>
				</div>
				{editable ? (
					<Button size="sm" onClick={() => void save()} disabled={update.isPending}>
						{update.isPending ? "Saving…" : "Save Details"}
					</Button>
				) : null}
			</div>

			<div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
				{FIELDS.map(({ key, label, kind, required }) => (
					<div className="grid gap-2" key={key}>
						<Label htmlFor={`run-report-${key}`}>
							<span>
								{label}
								{required ? (
									<span className="text-destructive" aria-hidden="true">
										&nbsp;*
									</span>
								) : null}
							</span>
						</Label>
						{kind === "date" ? (
							<DatePicker
								id={`run-report-${key}`}
								aria-label={required ? `${label} (required)` : label}
								value={form[key] ? parseApiDate(String(form[key])) : undefined}
								onValueChange={(date) => setField(key, date ? toApiDate(date) : null)}
								placeholder="Date"
								calendarProps={SCHEDULABLE_DATE_CALENDAR_PROPS}
								className="w-full"
								disabled={!editable || update.isPending}
							/>
						) : (
							<Input
								id={`run-report-${key}`}
								value={String(form[key] ?? "")}
								onChange={(event) => setField(key, event.target.value || null)}
								disabled={!editable || update.isPending}
								required={required}
							/>
						)}
					</div>
				))}
			</div>
		</PageSection>
	);
}
