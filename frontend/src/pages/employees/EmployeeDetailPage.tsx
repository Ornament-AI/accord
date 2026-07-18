import { type ReactNode, useMemo, useState } from "react";
import { Link, useParams } from "react-router";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { DataTableSkeleton } from "@/components/data-table-skeleton";
import { EmptyState } from "@/components/empty-state";
import { FieldsValueTable } from "@/components/fields-value-table";
import { PageSection, PageShell } from "@/components/page-shell";
import { Badge } from "@/components/ui/badge";
import {
	Breadcrumb,
	BreadcrumbItem,
	BreadcrumbLink,
	BreadcrumbList,
	BreadcrumbPage,
	BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/contexts/AuthContext";
import {
	type BankVersionResponse,
	type EmployeeVersionKind,
	type PayVersionResponse,
	type PostingVersionResponse,
	type ProfileVersionResponse,
	parseApiDate,
	toApiDate,
	todayApiDate,
	useEmployeeDetail,
} from "@/lib/api/employees";
import {
	useEmployeeGroupsList,
	useOfficesList,
	usePayrollUnitsList,
	usePostsList,
} from "@/lib/api/org-structure";
import { namedEntityLabel, postEntityLabel } from "@/lib/entity-labels";
import { getErrorMessage } from "@/lib/errors";
import { formatDate } from "@/lib/utils";

import { AccommodationTab } from "./payroll-setup/AccommodationTab";
import { AdvancesTab } from "./payroll-setup/AdvancesTab";
import { RecurringItemsTab } from "./payroll-setup/RecurringItemsTab";
import { ScheduleChangeDialog } from "./ScheduleChangeDialog";

type EmployeeDetailTab = EmployeeVersionKind | "recurring" | "advances" | "accommodation";

const VERSION_KINDS = new Set<EmployeeVersionKind>(["profile", "posting", "pay", "bank"]);

function isVersionKind(tab: EmployeeDetailTab): tab is EmployeeVersionKind {
	return VERSION_KINDS.has(tab as EmployeeVersionKind);
}

function regimeLabel(regime: string | null | undefined): string {
	if (!regime) return "—";
	return regime.toUpperCase();
}

function displayValue(value: string | number | boolean | null | undefined): string {
	if (value === null || value === undefined || value === "") return "—";
	if (typeof value === "boolean") return value ? "Yes" : "No";
	return String(value);
}

function labeledRef(
	id: string | null | undefined,
	lookup: Map<string, { name?: string | null; code?: string | null }>,
): string {
	if (!id) return "—";
	const item = lookup.get(id);
	return item ? namedEntityLabel(item, id) : id;
}

function labeledPostRef(
	id: string | null | undefined,
	lookup: Map<string, { designation?: string | null }>,
): string {
	if (!id) return "—";
	const item = lookup.get(id);
	return item ? postEntityLabel(item, id) : id;
}

function EmployeeBreadcrumb({ label }: { label: string }) {
	return (
		<Breadcrumb>
			<BreadcrumbList>
				<BreadcrumbItem>
					<BreadcrumbLink render={<Link to="/employees" />}>Employees</BreadcrumbLink>
				</BreadcrumbItem>
				<BreadcrumbSeparator />
				<BreadcrumbItem>
					<BreadcrumbPage>{label}</BreadcrumbPage>
				</BreadcrumbItem>
			</BreadcrumbList>
		</Breadcrumb>
	);
}

function SnapshotFieldsTable({
	emptyMessage,
	rows,
}: {
	emptyMessage: string;
	rows: Array<{ label: string; value: ReactNode }> | null;
}) {
	if (!rows) {
		return <p className="text-sm text-muted-foreground">{emptyMessage}</p>;
	}

	return (
		<div className="app-table-surface overflow-hidden rounded-lg">
			<FieldsValueTable rows={rows} />
		</div>
	);
}

function ProfileFieldsTable({ profile }: { profile: ProfileVersionResponse | null }) {
	if (!profile) {
		return <SnapshotFieldsTable emptyMessage="No active profile version." rows={null} />;
	}

	return (
		<SnapshotFieldsTable
			emptyMessage="No active profile version."
			rows={[
				{ label: "Name", value: displayValue(profile.name) },
				{ label: "Sevarth ID", value: displayValue(profile.sevarth_id) },
				{
					label: "Regime",
					value: <Badge variant="secondary">{regimeLabel(profile.retirement_regime)}</Badge>,
				},
				{ label: "GPF Jurisdiction", value: displayValue(profile.gpf_jurisdiction) },
				{ label: "PAN", value: displayValue(profile.pan) },
				{ label: "PRAN", value: displayValue(profile.pran) },
				{ label: "GPF Account", value: displayValue(profile.gpf_account_number) },
				{ label: "EPF Number", value: displayValue(profile.epf_number) },
				{ label: "Date of Birth", value: formatDate(profile.date_of_birth) },
				{ label: "Date of Joining", value: formatDate(profile.date_of_joining) },
				{ label: "Effective From", value: formatDate(profile.effective_from) },
			]}
		/>
	);
}

function PostingFieldsTable({
	posting,
	officeLabel,
	payrollUnitLabel,
	postLabel,
	employeeGroupLabel,
}: {
	posting: PostingVersionResponse | null;
	officeLabel: string;
	payrollUnitLabel: string;
	postLabel: string;
	employeeGroupLabel: string;
}) {
	if (!posting) {
		return <SnapshotFieldsTable emptyMessage="No active posting version." rows={null} />;
	}

	return (
		<SnapshotFieldsTable
			emptyMessage="No active posting version."
			rows={[
				{ label: "Office", value: officeLabel },
				{ label: "Payroll Unit", value: payrollUnitLabel },
				{ label: "Post", value: postLabel },
				{ label: "Employee Group", value: employeeGroupLabel },
				{ label: "Effective From", value: formatDate(posting.effective_from) },
			]}
		/>
	);
}

function PayFieldsTable({ pay }: { pay: PayVersionResponse | null }) {
	if (!pay) {
		return <SnapshotFieldsTable emptyMessage="No active pay version." rows={null} />;
	}

	return (
		<SnapshotFieldsTable
			emptyMessage="No active pay version."
			rows={[
				{ label: "Pay Matrix Level", value: displayValue(pay.pay_matrix_level) },
				{ label: "Basic Pay", value: displayValue(pay.basic_pay) },
				{ label: "Effective From", value: formatDate(pay.effective_from) },
			]}
		/>
	);
}

function BankFieldsTable({ bank }: { bank: BankVersionResponse | null }) {
	if (!bank) {
		return <SnapshotFieldsTable emptyMessage="No active bank version." rows={null} />;
	}

	return (
		<SnapshotFieldsTable
			emptyMessage="No active bank version."
			rows={[
				{ label: "Account Number", value: displayValue(bank.account_number) },
				{ label: "IFSC", value: displayValue(bank.ifsc) },
				{ label: "Bank Name", value: displayValue(bank.bank_name) },
				{ label: "Branch", value: displayValue(bank.branch) },
				{ label: "Primary Salary", value: displayValue(bank.is_primary_salary) },
				{ label: "Effective From", value: formatDate(bank.effective_from) },
			]}
		/>
	);
}

export default function EmployeeDetailPage() {
	const { employeeId } = useParams<{ employeeId: string }>();
	const { hasCapability } = useAuth();
	const canManage = hasCapability("manage_master_data");
	const canReveal = hasCapability("reveal_sensitive_fields");

	const [asOf, setAsOf] = useState(() => todayApiDate());
	const [reveal, setReveal] = useState(false);
	const [scheduleKind, setScheduleKind] = useState<EmployeeVersionKind | null>(null);
	const [activeTab, setActiveTab] = useState<EmployeeDetailTab>("profile");
	const [createOpen, setCreateOpen] = useState(false);

	const isPayrollSetupTab =
		activeTab === "recurring" || activeTab === "advances" || activeTab === "accommodation";

	const detailQuery = useEmployeeDetail(employeeId, {
		as_of: asOf,
		reveal: reveal && canReveal,
	});

	const officesQuery = useOfficesList();
	const payrollUnitsQuery = usePayrollUnitsList();
	const postsQuery = usePostsList();
	const employeeGroupsQuery = useEmployeeGroupsList();

	const asOfDate = useMemo(() => parseApiDate(asOf), [asOf]);
	const employee = detailQuery.data;
	const profile = employee?.profile ?? null;
	const posting = employee?.posting ?? null;
	const pay = employee?.pay ?? null;
	const bank = employee?.bank ?? null;

	const postingLabels = useMemo(() => {
		const offices = new Map((officesQuery.data ?? []).map((item) => [item.id, item]));
		const units = new Map((payrollUnitsQuery.data ?? []).map((item) => [item.id, item]));
		const posts = new Map((postsQuery.data ?? []).map((item) => [item.id, item]));
		const groups = new Map((employeeGroupsQuery.data ?? []).map((item) => [item.id, item]));

		return {
			officeLabel: labeledRef(posting?.office_id, offices),
			payrollUnitLabel: labeledRef(posting?.payroll_unit_id, units),
			postLabel: labeledPostRef(posting?.post_id, posts),
			employeeGroupLabel: labeledRef(posting?.employee_group_id, groups),
		};
	}, [
		posting,
		officesQuery.data,
		payrollUnitsQuery.data,
		postsQuery.data,
		employeeGroupsQuery.data,
	]);

	if (!employeeId) {
		return (
			<CapabilityGate capability="view_master_data" title="Employee">
				<AppLayout title="Employee">
					<PageShell>
						<EmptyState title="Employee not found" description="Missing employee id." />
					</PageShell>
				</AppLayout>
			</CapabilityGate>
		);
	}

	return (
		<CapabilityGate capability="view_master_data" title="Employee">
			<AppLayout
				title={employee ? <EmployeeBreadcrumb label={employee.employee_number} /> : "Employee"}
				actions={
					<div className="flex items-center gap-2">
						{canReveal ? (
							<Button
								size="xs"
								variant="outline"
								aria-pressed={reveal}
								aria-label={reveal ? "Hide Sensitive Fields" : "Reveal Sensitive Fields"}
								onClick={() => setReveal((prev) => !prev)}
							>
								{reveal ? "Hide" : "Reveal"}
							</Button>
						) : null}
						{canManage && isVersionKind(activeTab) ? (
							<Button size="xs" onClick={() => setScheduleKind(activeTab)}>
								Edit
							</Button>
						) : null}
						{canManage && isPayrollSetupTab ? (
							<Button size="xs" onClick={() => setCreateOpen(true)}>
								Add
							</Button>
						) : null}
					</div>
				}
			>
				<PageShell data-testid="employee-detail-page">
					{detailQuery.isLoading ? (
						<div className="grid gap-4">
							<Skeleton className="h-20 w-full" />
							<DataTableSkeleton />
						</div>
					) : null}

					{detailQuery.isError ? (
						<ErrorWithRetry
							message={getErrorMessage(detailQuery.error, "Failed to load employee.")}
							onRetry={() => void detailQuery.refetch()}
						/>
					) : null}

					{employee ? (
						<>
							<PageSection>
								<div className="flex flex-wrap items-center gap-3">
									<span className="text-xl font-semibold tracking-tight">
										{profile?.name ?? "—"}
									</span>
									{profile?.retirement_regime ? (
										<Badge variant="secondary">{regimeLabel(profile.retirement_regime)}</Badge>
									) : null}
								</div>
							</PageSection>

							<PageSection>
								<Tabs
									value={activeTab}
									onValueChange={(value) => {
										setActiveTab(value as EmployeeDetailTab);
										setCreateOpen(false);
									}}
									className="gap-0"
								>
									<div className="flex flex-wrap items-center justify-between gap-2">
										<TabsList className="h-9 group-data-horizontal/tabs:h-9">
											<TabsTrigger value="profile">Profile</TabsTrigger>
											<TabsTrigger value="posting">Posting</TabsTrigger>
											<TabsTrigger value="pay">Pay</TabsTrigger>
											<TabsTrigger value="bank">Bank</TabsTrigger>
											<TabsTrigger value="recurring">Recurring Items</TabsTrigger>
											<TabsTrigger value="advances">Advances</TabsTrigger>
											<TabsTrigger value="accommodation">Accommodation</TabsTrigger>
										</TabsList>
										<DatePicker
											value={asOfDate}
											onValueChange={(date) => {
												if (date) setAsOf(toApiDate(date));
											}}
											aria-label="As of Date"
											placeholder="As of"
										/>
									</div>

									<TabsContent value="profile" className="mt-2">
										<ProfileFieldsTable profile={profile} />
									</TabsContent>

									<TabsContent value="posting" className="mt-2">
										<PostingFieldsTable
											posting={posting}
											officeLabel={postingLabels.officeLabel}
											payrollUnitLabel={postingLabels.payrollUnitLabel}
											postLabel={postingLabels.postLabel}
											employeeGroupLabel={postingLabels.employeeGroupLabel}
										/>
									</TabsContent>

									<TabsContent value="pay" className="mt-2">
										<PayFieldsTable pay={pay} />
									</TabsContent>

									<TabsContent value="bank" className="mt-2">
										<BankFieldsTable bank={bank} />
									</TabsContent>

									<TabsContent value="recurring" className="mt-2">
										<RecurringItemsTab
											employeeId={employeeId}
											asOf={asOf}
											canManage={canManage}
											createOpen={createOpen && activeTab === "recurring"}
											onCreateOpenChange={setCreateOpen}
										/>
									</TabsContent>

									<TabsContent value="advances" className="mt-2">
										<AdvancesTab
											employeeId={employeeId}
											asOf={asOf}
											canManage={canManage}
											createOpen={createOpen && activeTab === "advances"}
											onCreateOpenChange={setCreateOpen}
										/>
									</TabsContent>

									<TabsContent value="accommodation" className="mt-2">
										<AccommodationTab
											employeeId={employeeId}
											asOf={asOf}
											canManage={canManage}
											createOpen={createOpen && activeTab === "accommodation"}
											onCreateOpenChange={setCreateOpen}
										/>
									</TabsContent>
								</Tabs>
							</PageSection>
						</>
					) : null}
				</PageShell>

				{scheduleKind && employeeId ? (
					<ScheduleChangeDialog
						open={Boolean(scheduleKind)}
						onOpenChange={(open) => {
							if (!open) setScheduleKind(null);
						}}
						employeeId={employeeId}
						kind={scheduleKind}
						activeProfile={profile}
						activePosting={posting}
						activePay={pay}
						activeBank={bank}
					/>
				) : null}
			</AppLayout>
		</CapabilityGate>
	);
}
