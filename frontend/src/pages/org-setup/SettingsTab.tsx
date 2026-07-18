import { type FormEvent, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	type OrganizationSettingsUpdate,
	useOrganizationSettings,
	useUpdateOrganizationSettings,
} from "@/lib/api/org-structure";
import { ApiError, getErrorMessage } from "@/lib/errors";

import { parseFieldErrors } from "./parse-field-errors";

type FormState = {
	locale: string;
	timezone: string;
	currency: string;
	financial_year_start_month: string;
};

const emptyForm = (): FormState => ({
	locale: "",
	timezone: "",
	currency: "",
	financial_year_start_month: "",
});

export function SettingsTab() {
	const settingsQuery = useOrganizationSettings();
	const updateSettings = useUpdateOrganizationSettings();
	const [form, setForm] = useState<FormState>(emptyForm);
	const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (!settingsQuery.data) return;
		setForm({
			locale: settingsQuery.data.locale,
			timezone: settingsQuery.data.timezone,
			currency: settingsQuery.data.currency,
			financial_year_start_month: String(settingsQuery.data.financial_year_start_month),
		});
		setFieldErrors({});
		setFormError(null);
	}, [settingsQuery.data]);

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setFieldErrors({});
		setFormError(null);

		const month = Number(form.financial_year_start_month);
		if (!Number.isInteger(month) || month < 1 || month > 12) {
			setFieldErrors({ financial_year_start_month: "Must be a month between 1 and 12" });
			return;
		}

		const body: OrganizationSettingsUpdate = {
			locale: form.locale.trim(),
			timezone: form.timezone.trim(),
			currency: form.currency.trim(),
			financial_year_start_month: month,
		};

		try {
			await updateSettings.mutateAsync(body);
			toast.success("Organization settings saved");
		} catch (error) {
			if (error instanceof ApiError && error.status === 422) {
				const parsed = parseFieldErrors(error);
				if (Object.keys(parsed).length > 0) {
					setFieldErrors(parsed);
					return;
				}
			}
			setFormError(
				error instanceof Error ? error.message : "Unable to save organization settings.",
			);
		}
	};

	if (settingsQuery.isLoading) {
		return <p className="text-sm text-muted-foreground">Loading settings…</p>;
	}

	if (settingsQuery.isError) {
		return (
			<ErrorWithRetry
				message={getErrorMessage(settingsQuery.error, "Failed to load organization settings.")}
				onRetry={() => void settingsQuery.refetch()}
			/>
		);
	}

	const isSubmitting = updateSettings.isPending;

	return (
		<form
			onSubmit={(event) => void handleSubmit(event)}
			className="grid max-w-lg gap-4"
			data-testid="settings-tab"
		>
			<div className="grid gap-2">
				<Label htmlFor="settings-locale">Locale</Label>
				<Input
					id="settings-locale"
					value={form.locale}
					onChange={(event) => {
						setForm((prev) => ({ ...prev, locale: event.target.value }));
						setFieldErrors((prev) => {
							const next = { ...prev };
							delete next.locale;
							return next;
						});
					}}
					disabled={isSubmitting}
					aria-invalid={fieldErrors.locale ? true : undefined}
				/>
				{fieldErrors.locale ? (
					<p className="text-sm text-destructive">{fieldErrors.locale}</p>
				) : null}
			</div>

			<div className="grid gap-2">
				<Label htmlFor="settings-timezone">Timezone</Label>
				<Input
					id="settings-timezone"
					value={form.timezone}
					onChange={(event) => {
						setForm((prev) => ({ ...prev, timezone: event.target.value }));
						setFieldErrors((prev) => {
							const next = { ...prev };
							delete next.timezone;
							return next;
						});
					}}
					disabled={isSubmitting}
					aria-invalid={fieldErrors.timezone ? true : undefined}
				/>
				{fieldErrors.timezone ? (
					<p className="text-sm text-destructive">{fieldErrors.timezone}</p>
				) : null}
			</div>

			<div className="grid gap-2">
				<Label htmlFor="settings-currency">Currency</Label>
				<Input
					id="settings-currency"
					value={form.currency}
					onChange={(event) => {
						setForm((prev) => ({ ...prev, currency: event.target.value }));
						setFieldErrors((prev) => {
							const next = { ...prev };
							delete next.currency;
							return next;
						});
					}}
					disabled={isSubmitting}
					aria-invalid={fieldErrors.currency ? true : undefined}
				/>
				{fieldErrors.currency ? (
					<p className="text-sm text-destructive">{fieldErrors.currency}</p>
				) : null}
			</div>

			<div className="grid gap-2">
				<Label htmlFor="settings-fy-start">Financial year start month</Label>
				<Input
					id="settings-fy-start"
					type="number"
					min={1}
					max={12}
					value={form.financial_year_start_month}
					onChange={(event) => {
						setForm((prev) => ({
							...prev,
							financial_year_start_month: event.target.value,
						}));
						setFieldErrors((prev) => {
							const next = { ...prev };
							delete next.financial_year_start_month;
							return next;
						});
					}}
					disabled={isSubmitting}
					aria-invalid={fieldErrors.financial_year_start_month ? true : undefined}
				/>
				{fieldErrors.financial_year_start_month ? (
					<p className="text-sm text-destructive">{fieldErrors.financial_year_start_month}</p>
				) : null}
			</div>

			{formError ? <p className="text-sm text-destructive">{formError}</p> : null}

			<div>
				<Button type="submit" disabled={isSubmitting}>
					{isSubmitting ? "Saving…" : "Save settings"}
				</Button>
			</div>
		</form>
	);
}
