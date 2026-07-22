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
import { Switch } from "@/components/ui/switch";
import {
	classificationLabel,
	type PayComponentResponse,
	REGISTER_COLUMNS_BY_CLASSIFICATION,
	type RegisterColumn,
	registerColumnLabel,
	type ScheduleKind,
	usePayComponentsList,
	useUpdatePayComponent,
} from "@/lib/api/pay-setup";
import { DIALOG_CONTENT_CLASSNAMES } from "@/lib/dialog-sizes";
import { ApiError } from "@/lib/errors";

type EditPayComponentDialogProps = {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	component: PayComponentResponse | null;
};

type FormState = {
	name: string;
	display_order: string;
	register_column: RegisterColumn | "";
	is_active: boolean;
	employer_transfer: boolean;
	transfer_of: string;
	schedule_kind: ScheduleKind | "";
	schedule_title: string;
	schedule_account_head: string;
};

const OFF_BILL_VALUE = "__offbill__";

export function EditPayComponentDialog({
	open,
	onOpenChange,
	component,
}: EditPayComponentDialogProps) {
	const updateComponent = useUpdatePayComponent();
	const componentsQuery = usePayComponentsList();
	const [form, setForm] = useState<FormState>({
		name: "",
		display_order: "0",
		register_column: "",
		is_active: true,
		employer_transfer: false,
		transfer_of: "",
		schedule_kind: "",
		schedule_title: "",
		schedule_account_head: "",
	});
	const [formError, setFormError] = useState<string | null>(null);

	useEffect(() => {
		if (open && component) {
			setForm({
				name: component.name,
				display_order: String(component.display_order),
				register_column: component.register_column ?? "",
				is_active: component.is_active,
				employer_transfer: component.employer_transfer,
				transfer_of: component.transfer_of ?? "",
				schedule_kind: (component.schedule_kind as ScheduleKind | null) ?? "",
				schedule_title: component.schedule_title ?? "",
				schedule_account_head: component.schedule_account_head ?? "",
			});
			setFormError(null);
		}
	}, [open, component]);

	const handleSubmit = async (event: FormEvent) => {
		event.preventDefault();
		if (!component) return;
		setFormError(null);

		if (!form.name.trim()) {
			setFormError("Name is required.");
			return;
		}

		const displayOrder = Number(form.display_order);
		if (!Number.isFinite(displayOrder)) {
			setFormError("Display order must be a number.");
			return;
		}

		try {
			await updateComponent.mutateAsync({
				componentId: component.id,
				body: {
					name: form.name.trim(),
					display_order: displayOrder,
					register_column: form.register_column || null,
					...(component.is_standard ? {} : { is_active: form.is_active }),
					employer_transfer: form.employer_transfer,
					transfer_of: form.employer_transfer ? form.transfer_of || null : null,
					schedule_kind: form.schedule_kind || null,
					schedule_title: form.schedule_kind ? form.schedule_title.trim() || null : null,
					schedule_account_head: form.schedule_kind
						? form.schedule_account_head.trim() || null
						: null,
				},
			});
			onOpenChange(false);
		} catch (error) {
			setFormError(
				error instanceof ApiError
					? error.detail
					: error instanceof Error
						? error.message
						: "Failed to update pay component.",
			);
		}
	};

	const isSubmitting = updateComponent.isPending;
	const employerContributions = (componentsQuery.data ?? []).filter(
		(item) => item.classification === "employer_contribution" && item.is_active,
	);
	const registerColumns = (
		component
			? REGISTER_COLUMNS_BY_CLASSIFICATION[
					component.classification as keyof typeof REGISTER_COLUMNS_BY_CLASSIFICATION
				]
			: []
	) as readonly RegisterColumn[];

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className={DIALOG_CONTENT_CLASSNAMES.compactForm}>
				<DialogHeader className="px-6 pt-5 pb-3">
					<DialogTitle>Edit Pay Component</DialogTitle>
					<DialogDescription>
						Update presentation and export settings. Code and classification are fixed.
					</DialogDescription>
				</DialogHeader>

				{component ? (
					<form
						className="flex min-h-0 flex-1 flex-col"
						onSubmit={(event) => void handleSubmit(event)}
					>
						<DialogBody className="grid gap-4 pb-8">
							<div className="grid gap-2">
								<Label htmlFor="edit-pc-code">Code</Label>
								<Input id="edit-pc-code" value={component.code} readOnly disabled />
							</div>

							{!component.is_standard ? (
								<div className="flex items-center justify-between gap-4">
									<div className="grid gap-1">
										<Label htmlFor="edit-pc-active">Active</Label>
										<p className="text-xs text-muted-foreground">
											Inactive components are hidden from new payroll setup.
										</p>
									</div>
									<Switch
										id="edit-pc-active"
										checked={form.is_active}
										onCheckedChange={(checked) =>
											setForm((prev) => ({ ...prev, is_active: checked }))
										}
										disabled={isSubmitting}
									/>
								</div>
							) : null}

							<div className="grid gap-2">
								<Label htmlFor="edit-pc-classification">Classification</Label>
								<Input
									id="edit-pc-classification"
									value={classificationLabel(component.classification)}
									readOnly
									disabled
								/>
							</div>

							<div className="grid gap-2">
								<Label htmlFor="edit-pc-name">Name</Label>
								<Input
									id="edit-pc-name"
									value={form.name}
									onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
									disabled={isSubmitting}
								/>
							</div>

							<div className="grid gap-2">
								<Label htmlFor="edit-pc-register-column">Pay Bill Column</Label>
								<Select
									value={form.register_column || "none"}
									onValueChange={(value) =>
										setForm((prev) => ({
											...prev,
											register_column: value === "none" ? "" : (value as RegisterColumn),
										}))
									}
									disabled={isSubmitting || registerColumns.length === 0}
								>
									<SelectTrigger id="edit-pc-register-column" className="w-full">
										<SelectValue placeholder="Not shown in Pay Bill" />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="none">Not shown in Pay Bill</SelectItem>
										{registerColumns.map((column) => (
											<SelectItem key={column} value={column}>
												{registerColumnLabel(column)}
											</SelectItem>
										))}
									</SelectContent>
								</Select>
							</div>

							<div className="grid gap-2">
								<Label htmlFor="edit-pc-display-order">Display Order</Label>
								<Input
									id="edit-pc-display-order"
									type="number"
									value={form.display_order}
									onChange={(event) =>
										setForm((prev) => ({ ...prev, display_order: event.target.value }))
									}
									disabled={isSubmitting}
								/>
							</div>

							<div className="grid gap-2">
								<Label htmlFor="edit-pc-schedule-kind">Export Schedule</Label>
								<Select
									value={form.schedule_kind || "none"}
									onValueChange={(value) =>
										setForm((prev) => ({
											...prev,
											schedule_kind: value === "none" ? "" : (value as ScheduleKind),
										}))
									}
									disabled={isSubmitting}
								>
									<SelectTrigger id="edit-pc-schedule-kind" className="w-full">
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="none">No separate schedule</SelectItem>
										<SelectItem value="simple_component">Component schedule</SelectItem>
										<SelectItem value="loan_installment">Loan installment schedule</SelectItem>
									</SelectContent>
								</Select>
							</div>

							{form.schedule_kind ? (
								<>
									<div className="grid gap-2">
										<Label htmlFor="edit-pc-schedule-title">Schedule Title</Label>
										<Input
											id="edit-pc-schedule-title"
											value={form.schedule_title}
											onChange={(event) =>
												setForm((prev) => ({
													...prev,
													schedule_title: event.target.value,
												}))
											}
											disabled={isSubmitting || component.is_standard}
										/>
									</div>
									<div className="grid gap-2">
										<Label htmlFor="edit-pc-schedule-account-head">Account Head</Label>
										<Input
											id="edit-pc-schedule-account-head"
											value={form.schedule_account_head}
											onChange={(event) =>
												setForm((prev) => ({
													...prev,
													schedule_account_head: event.target.value,
												}))
											}
											disabled={isSubmitting}
										/>
									</div>
								</>
							) : null}

							{["ag_deduction", "treasury_deduction", "external_recovery"].includes(
								component.classification,
							) ? (
								<>
									<div className="flex items-center justify-between gap-4">
										<div className="grid gap-1">
											<Label htmlFor="edit-pc-employer-transfer">Employer Transfer</Label>
											<p className="text-xs text-muted-foreground">
												Marks an employer-funded deduction.
											</p>
										</div>
										<Switch
											id="edit-pc-employer-transfer"
											checked={form.employer_transfer}
											onCheckedChange={(checked) =>
												setForm((prev) => ({
													...prev,
													employer_transfer: checked,
													transfer_of: checked ? prev.transfer_of : "",
												}))
											}
											disabled={isSubmitting}
										/>
									</div>

									{form.employer_transfer ? (
										<div className="grid gap-2">
											<Label htmlFor="edit-pc-transfer-of">Paired Employer Contribution</Label>
											<Select
												value={form.transfer_of || OFF_BILL_VALUE}
												onValueChange={(value) =>
													setForm((prev) => ({
														...prev,
														transfer_of: value === OFF_BILL_VALUE ? "" : value,
													}))
												}
												disabled={isSubmitting || component.is_standard}
											>
												<SelectTrigger id="edit-pc-transfer-of" className="w-full">
													<SelectValue />
												</SelectTrigger>
												<SelectContent>
													<SelectItem value={OFF_BILL_VALUE}>None (off-bill)</SelectItem>
													{employerContributions.map((item) => (
														<SelectItem key={item.id} value={item.code}>
															{item.name} ({item.code})
														</SelectItem>
													))}
												</SelectContent>
											</Select>
										</div>
									) : null}
								</>
							) : null}

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
								{isSubmitting ? "Saving…" : "Save"}
							</Button>
						</DialogFooter>
					</form>
				) : null}
			</DialogContent>
		</Dialog>
	);
}
