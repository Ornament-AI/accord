import { Eye, EyeOff } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { Link, useParams } from "react-router";

import { AppLayout } from "@/components/app-layout";
import { CapabilityGate } from "@/components/capability-gate";
import { EmptyState } from "@/components/empty-state";
import { PageSection, PageShell } from "@/components/page-shell";
import { PageToolbar } from "@/components/page-toolbar";
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
	useEmployeeVersions,
} from "@/lib/api/employees";
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

function FieldRow({ label, value }: { label: string; value: ReactNode }) {
	return (
		<div className="grid grid-cols-[10rem_1fr] gap-2 text-sm">
			<dt className="text-muted-foreground">{label}</dt>
			<dd className="min-w-0 break-words text-foreground">{value ?? "—"}</dd>
		</div>
	);
}

function VersionHistoryList({
	versions,
	isLoading,
}: {
	versions: Array<{
		id: string;
		effective_from: string;
		effective_to?: string | null;
		change_reason?: string | null;
	}>;
	isLoading: boolean;
}) {
	if (isLoading) {
		return (
			<div className="grid gap-2">
				<Skeleton className="h-10 w-full" />
				<Skeleton className="h-10 w-full" />
			</div>
		);
	}
	if (versions.length === 0) {
		return <p className="text-sm text-muted-foreground">No version history.</p>;
	}
	return (
		<ul className="grid gap-2">
			{versions.map((version) => (
				<li key={version.id} className="rounded-md border app-border-level-1 px-3 py-2 text-sm">
					<div className="font-medium">
						{formatDate(version.effective_from)}
						{version.effective_to ? ` → ${formatDate(version.effective_to)}` : " → present"}
					</div>
					{version.change_reason ? (
						<p className="mt-1 text-muted-foreground">{version.change_reason}</p>
					) : null}
				</li>
			))}
		</ul>
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

	const detailQuery = useEmployeeDetail(employeeId, {
		as_of: asOf,
		reveal: reveal && canReveal,
	});
	const versionKind = isVersionKind(activeTab) ? activeTab : "profile";
	const versionsQuery = useEmployeeVersions(
		isVersionKind(activeTab) ? employeeId : undefined,
		versionKind,
		reveal && canReveal,
	);

	const asOfDate = useMemo(() => parseApiDate(asOf), [asOf]);
	const employee = detailQuery.data;
	const profile = employee?.profile ?? null;
	const posting = employee?.posting ?? null;
	const pay = employee?.pay ?? null;
	const bank = employee?.bank ?? null;

	const versions = (versionsQuery.data ?? []) as Array<{
		id: string;
		effective_from: string;
		effective_to?: string | null;
		change_reason?: string | null;
	}>;

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
								size="sm"
								variant="outline"
								aria-pressed={reveal}
								aria-label={reveal ? "Hide sensitive fields" : "Reveal sensitive fields"}
								onClick={() => setReveal((prev) => !prev)}
							>
								{reveal ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
								{reveal ? "Hide" : "Reveal"}
							</Button>
						) : null}
					</div>
				}
			>
				<PageShell data-testid="employee-detail-page">
					<PageToolbar>
						<DatePicker
							value={asOfDate}
							onValueChange={(date) => {
								if (date) setAsOf(toApiDate(date));
							}}
							aria-label="As of date"
							placeholder="As of"
						/>
					</PageToolbar>

					{detailQuery.isLoading ? (
						<div className="grid gap-4">
							<Skeleton className="h-28 w-full" />
							<Skeleton className="h-64 w-full" />
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
									<h2 className="text-xl font-semibold tracking-tight">
										{employee.employee_number}
									</h2>
									<span className="text-muted-foreground">{profile?.name ?? "—"}</span>
									{profile?.retirement_regime ? (
										<Badge variant="secondary">{regimeLabel(profile.retirement_regime)}</Badge>
									) : null}
								</div>
								<p className="mt-1 text-sm text-muted-foreground">
									As of {formatDate(employee.as_of)}
								</p>
							</PageSection>

							<PageSection>
								<Tabs
									value={activeTab}
									onValueChange={(value) => setActiveTab(value as EmployeeDetailTab)}
								>
									<div className="flex flex-wrap items-center justify-between gap-2">
										<TabsList variant="line">
											<TabsTrigger value="profile">Profile</TabsTrigger>
											<TabsTrigger value="posting">Posting</TabsTrigger>
											<TabsTrigger value="pay">Pay</TabsTrigger>
											<TabsTrigger value="bank">Bank</TabsTrigger>
											<TabsTrigger value="recurring">Recurring Items</TabsTrigger>
											<TabsTrigger value="advances">Advances</TabsTrigger>
											<TabsTrigger value="accommodation">Accommodation</TabsTrigger>
										</TabsList>
										{canManage && isVersionKind(activeTab) ? (
											<Button size="sm" onClick={() => setScheduleKind(activeTab)}>
												Schedule change
											</Button>
										) : null}
									</div>

									<TabsContent value="profile" className="mt-4 grid gap-6">
										<ProfileFields profile={profile} />
										<div className="grid gap-2">
											<h3 className="text-sm font-medium">Version history</h3>
											<VersionHistoryList versions={versions} isLoading={versionsQuery.isLoading} />
										</div>
									</TabsContent>

									<TabsContent value="posting" className="mt-4 grid gap-6">
										<PostingFields posting={posting} />
										<div className="grid gap-2">
											<h3 className="text-sm font-medium">Version history</h3>
											<VersionHistoryList versions={versions} isLoading={versionsQuery.isLoading} />
										</div>
									</TabsContent>

									<TabsContent value="pay" className="mt-4 grid gap-6">
										<PayFields pay={pay} />
										<div className="grid gap-2">
											<h3 className="text-sm font-medium">Version history</h3>
											<VersionHistoryList versions={versions} isLoading={versionsQuery.isLoading} />
										</div>
									</TabsContent>

									<TabsContent value="bank" className="mt-4 grid gap-6">
										<BankFields bank={bank} />
										<div className="grid gap-2">
											<h3 className="text-sm font-medium">Version history</h3>
											<VersionHistoryList versions={versions} isLoading={versionsQuery.isLoading} />
										</div>
									</TabsContent>

									<TabsContent value="recurring" className="mt-4">
										<RecurringItemsTab employeeId={employeeId} asOf={asOf} canManage={canManage} />
									</TabsContent>

									<TabsContent value="advances" className="mt-4">
										<AdvancesTab employeeId={employeeId} asOf={asOf} canManage={canManage} />
									</TabsContent>

									<TabsContent value="accommodation" className="mt-4">
										<AccommodationTab employeeId={employeeId} asOf={asOf} canManage={canManage} />
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

function ProfileFields({ profile }: { profile: ProfileVersionResponse | null }) {
	if (!profile) {
		return <p className="text-sm text-muted-foreground">No active profile version.</p>;
	}
	return (
		<dl className="grid gap-3">
			<FieldRow label="Name" value={profile.name} />
			<FieldRow label="Sevarth ID" value={profile.sevarth_id} />
			<FieldRow label="Regime" value={regimeLabel(profile.retirement_regime)} />
			<FieldRow label="GPF jurisdiction" value={profile.gpf_jurisdiction} />
			<FieldRow label="PAN" value={profile.pan} />
			<FieldRow label="PRAN" value={profile.pran} />
			<FieldRow label="GPF account" value={profile.gpf_account_number} />
			<FieldRow label="EPF number" value={profile.epf_number} />
			<FieldRow label="Date of birth" value={formatDate(profile.date_of_birth)} />
			<FieldRow label="Date of joining" value={formatDate(profile.date_of_joining)} />
			<FieldRow label="Effective from" value={formatDate(profile.effective_from)} />
		</dl>
	);
}

function PostingFields({ posting }: { posting: PostingVersionResponse | null }) {
	if (!posting) {
		return <p className="text-sm text-muted-foreground">No active posting version.</p>;
	}
	return (
		<dl className="grid gap-3">
			<FieldRow label="Office ID" value={posting.office_id} />
			<FieldRow label="Payroll unit ID" value={posting.payroll_unit_id} />
			<FieldRow label="Post ID" value={posting.post_id} />
			<FieldRow label="Employee group ID" value={posting.employee_group_id} />
			<FieldRow label="Effective from" value={formatDate(posting.effective_from)} />
		</dl>
	);
}

function PayFields({ pay }: { pay: PayVersionResponse | null }) {
	if (!pay) {
		return <p className="text-sm text-muted-foreground">No active pay version.</p>;
	}
	return (
		<dl className="grid gap-3">
			<FieldRow label="Pay matrix level" value={pay.pay_matrix_level} />
			<FieldRow label="Basic pay" value={pay.basic_pay} />
			<FieldRow label="Effective from" value={formatDate(pay.effective_from)} />
		</dl>
	);
}

function BankFields({ bank }: { bank: BankVersionResponse | null }) {
	if (!bank) {
		return <p className="text-sm text-muted-foreground">No active bank version.</p>;
	}
	return (
		<dl className="grid gap-3">
			<FieldRow label="Account number" value={bank.account_number} />
			<FieldRow label="IFSC" value={bank.ifsc} />
			<FieldRow label="Bank name" value={bank.bank_name} />
			<FieldRow label="Branch" value={bank.branch} />
			<FieldRow label="Primary salary" value={bank.is_primary_salary ? "Yes" : "No"} />
			<FieldRow label="Effective from" value={formatDate(bank.effective_from)} />
		</dl>
	);
}
