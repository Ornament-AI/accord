import { type ColumnDef, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import {
	forwardRef,
	useCallback,
	useDeferredValue,
	useEffect,
	useImperativeHandle,
	useMemo,
	useState,
} from "react";
import { toast } from "sonner";

import { usePersistedColumnVisibility } from "@/components/column-visibility";
import { DataSearchControl } from "@/components/data-search-control";
import { DataTableShell } from "@/components/data-table-shell";
import { PageToolbar } from "@/components/page-toolbar";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { ErrorWithRetry } from "@/components/ui/error-with-retry";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
	formatCanonicalMoney,
	isDraftStatus,
	type PayrollRunEmployeeResponse,
	usePayrollRunResults,
	usePayrollRunRoster,
	useReplacePayrollRunRoster,
} from "@/lib/api/payroll-runs";
import { getErrorMessage } from "@/lib/errors";

type EditableRosterRow = PayrollRunEmployeeResponse & {
	payable_days: string;
	da_percent: string | null;
	da_difference: string | null;
	hra_percent: string | null;
	transport_amount: string | null;
};

type EditableField =
	| "payable_days"
	| "da_percent"
	| "da_difference"
	| "hra_percent"
	| "transport_amount";

function toEditableRows(rows: PayrollRunEmployeeResponse[]): EditableRosterRow[] {
	return rows.map((row) => ({
		...row,
		da_percent: row.da_percent ?? null,
		da_difference: row.da_difference ?? null,
		hra_percent: row.hra_percent ?? null,
		transport_amount: row.transport_amount ?? null,
	}));
}

function optionalDecimal(value: string | null): string | null {
	const trimmed = value?.trim() ?? "";
	return trimmed || null;
}

function parseDecimal(value: string | null | undefined): number | null {
	const trimmed = value?.trim() ?? "";
	if (!trimmed) return null;
	if (!/^-?\d+(?:\.\d+)?$/.test(trimmed)) return null;
	const parsed = Number(trimmed);
	return Number.isFinite(parsed) ? parsed : null;
}

function roundMoney(value: number): number {
	return Math.round((value + Number.EPSILON) * 100) / 100;
}

/**
 * Draft-only preview of prorated basic plus amounts derived from entered roster
 * overrides. Omits recurring items, deductions, and other engine inputs — never
 * use this as a calculated/final payroll total.
 */
function computeRosterPreviewTotal(row: EditableRosterRow, periodDays: number): number | null {
	const basicPay = parseDecimal(row.basic_pay);
	const payableDays = parseDecimal(row.payable_days);
	if (basicPay === null || payableDays === null || periodDays <= 0) return null;

	const proratedBasic = roundMoney((basicPay * payableDays) / periodDays);
	let total = proratedBasic;

	const daPercent = parseDecimal(row.da_percent);
	if (daPercent !== null) {
		total = roundMoney(total + (proratedBasic * daPercent) / 100);
	}

	const daDifference = parseDecimal(row.da_difference);
	if (daDifference !== null) {
		total = roundMoney(total + daDifference);
	}

	const hraPercent = parseDecimal(row.hra_percent);
	if (hraPercent !== null) {
		total = roundMoney(total + (proratedBasic * hraPercent) / 100);
	}

	const transport = parseDecimal(row.transport_amount);
	if (transport !== null) {
		total = roundMoney(total + transport);
	}

	return total;
}

function formatTotalMoney(value: string | number | null): string {
	if (value === null) return "—";
	if (typeof value === "string") return formatCanonicalMoney(value);
	return formatCanonicalMoney(value.toFixed(2));
}

function regimeLabel(regime: string | null | undefined): string {
	if (!regime) return "—";
	return regime.toUpperCase();
}

function PayrollGridInput({
	label,
	value,
	disabled,
	placeholder,
	onChange,
}: {
	label: string;
	value: string | null;
	disabled: boolean;
	placeholder?: string;
	onChange: (value: string) => void;
}) {
	return (
		<Input
			type="text"
			inputMode="decimal"
			aria-label={label}
			value={value ?? ""}
			disabled={disabled}
			placeholder={placeholder}
			className="h-8 min-w-20 px-2 text-center font-mono tabular-nums"
			onChange={(event) => onChange(event.target.value)}
		/>
	);
}

type RosterColumnsArgs = {
	editable: boolean;
	periodDays: number;
	/** When set, Total shows immutable calculated net payable instead of draft preview. */
	netPayableByEmployeeId: Map<string, string> | null;
	allSelected: boolean;
	setAllSelected: (selected: boolean) => void;
	updateRow: (employeeId: string, update: (row: EditableRosterRow) => EditableRosterRow) => void;
	updateField: (employeeId: string, field: EditableField, value: string) => void;
};

function buildRosterColumns({
	editable,
	periodDays,
	netPayableByEmployeeId,
	allSelected,
	setAllSelected,
	updateRow,
	updateField,
}: RosterColumnsArgs): ColumnDef<EditableRosterRow>[] {
	return [
		{
			id: "selected",
			header: () => (
				<Checkbox
					checked={allSelected}
					disabled={!editable}
					aria-label={allSelected ? "Clear Selection" : "Select All Employees"}
					onCheckedChange={editable ? (checked) => setAllSelected(checked) : undefined}
				/>
			),
			enableHiding: false,
			meta: {
				align: "center",
				hideFromColumnVisibilityToggle: true,
				className: "w-12 px-3 [&:has([role=checkbox])]:pr-3",
			},
			cell: ({ row }) => {
				const employeeLabel = row.original.employee_name || row.original.employee_number;
				return (
					<Checkbox
						checked={row.original.selected}
						disabled={!editable}
						aria-label={`Include ${employeeLabel}`}
						onCheckedChange={
							editable
								? (checked) =>
										updateRow(row.original.employee_id, (current) => ({
											...current,
											selected: checked,
										}))
								: undefined
						}
					/>
				);
			},
		},
		{
			id: "employee",
			accessorKey: "employee_name",
			header: "Employee",
			enableHiding: false,
			cell: ({ row }) => row.original.employee_name || "Unnamed employee",
		},
		{
			accessorKey: "sevarth_id",
			header: "Sevarth ID",
			cell: ({ row }) => row.original.sevarth_id || "—",
			meta: { className: "font-mono tabular-nums text-muted-foreground", label: "Sevarth ID" },
		},
		{
			accessorKey: "retirement_regime",
			header: "Regime",
			cell: ({ row }) => {
				const regime = row.original.retirement_regime;
				if (!regime) return "—";
				return <Badge variant="secondary">{regimeLabel(regime)}</Badge>;
			},
			meta: { align: "center", label: "Regime" },
		},
		{
			accessorKey: "basic_pay",
			header: "Basic Pay",
			cell: ({ row }) => (
				<span className="font-mono tabular-nums">
					{formatCanonicalMoney(row.original.basic_pay)}
				</span>
			),
			meta: { align: "right", label: "Basic Pay" },
		},
		{
			accessorKey: "payable_days",
			header: "Paid Days",
			cell: ({ row }) => {
				const employeeLabel = row.original.employee_name || row.original.employee_number;
				return (
					<PayrollGridInput
						label={`Paid Days for ${employeeLabel}`}
						value={row.original.payable_days}
						disabled={!editable}
						onChange={(value) => updateField(row.original.employee_id, "payable_days", value)}
					/>
				);
			},
			meta: { align: "center", label: "Paid Days" },
		},
		{
			accessorKey: "da_percent",
			header: "DA %",
			cell: ({ row }) => {
				const employeeLabel = row.original.employee_name || row.original.employee_number;
				return (
					<PayrollGridInput
						label={`DA Percent for ${employeeLabel}`}
						value={row.original.da_percent}
						disabled={!editable}
						placeholder="—"
						onChange={(value) => updateField(row.original.employee_id, "da_percent", value)}
					/>
				);
			},
			meta: { align: "center", label: "DA %" },
		},
		{
			accessorKey: "da_difference",
			header: "DA Difference",
			cell: ({ row }) => {
				const employeeLabel = row.original.employee_name || row.original.employee_number;
				return (
					<PayrollGridInput
						label={`DA Difference for ${employeeLabel}`}
						value={row.original.da_difference}
						disabled={!editable}
						placeholder="—"
						onChange={(value) => updateField(row.original.employee_id, "da_difference", value)}
					/>
				);
			},
			meta: { align: "center", label: "DA Difference" },
		},
		{
			accessorKey: "hra_percent",
			header: "HRA %",
			cell: ({ row }) => {
				const employeeLabel = row.original.employee_name || row.original.employee_number;
				return (
					<PayrollGridInput
						label={`HRA Percent for ${employeeLabel}`}
						value={row.original.hra_percent}
						disabled={!editable}
						placeholder="—"
						onChange={(value) => updateField(row.original.employee_id, "hra_percent", value)}
					/>
				);
			},
			meta: { align: "center", label: "HRA %" },
		},
		{
			accessorKey: "transport_amount",
			header: "Transport",
			cell: ({ row }) => {
				const employeeLabel = row.original.employee_name || row.original.employee_number;
				return (
					<PayrollGridInput
						label={`Transport Amount for ${employeeLabel}`}
						value={row.original.transport_amount}
						disabled={!editable}
						placeholder="—"
						onChange={(value) => updateField(row.original.employee_id, "transport_amount", value)}
					/>
				);
			},
			meta: { align: "center", label: "Transport" },
		},
		{
			id: "total",
			header: "Total",
			enableHiding: false,
			cell: ({ row }) => {
				const calculated = netPayableByEmployeeId?.get(row.original.employee_id) ?? null;
				const value =
					netPayableByEmployeeId !== null
						? calculated
						: computeRosterPreviewTotal(row.original, periodDays);
				return (
					<span className="font-mono font-medium tabular-nums">{formatTotalMoney(value)}</span>
				);
			},
			meta: { align: "right", label: "Total" },
		},
	];
}

function daysInPeriod(periodYear: number, periodMonth: number): number {
	return new Date(periodYear, periodMonth, 0).getDate();
}

export type PayrollRunRosterTableHandle = {
	cancel: () => void;
	save: () => Promise<boolean>;
};

type PayrollRunRosterTableProps = {
	runId: string;
	runStatus: string;
	editable: boolean;
	editing: boolean;
	periodYear: number;
	periodMonth: number;
	onDirtyChange: (dirty: boolean) => void;
};

export const PayrollRunRosterTable = forwardRef<
	PayrollRunRosterTableHandle,
	PayrollRunRosterTableProps
>(function PayrollRunRosterTable(
	{ runId, runStatus, editable, editing, periodYear, periodMonth, onDirtyChange },
	ref,
) {
	const rosterQuery = usePayrollRunRoster(runId);
	const replaceRoster = useReplacePayrollRunRoster(runId);
	const showCalculatedTotals = !isDraftStatus(runStatus);
	const resultsQuery = usePayrollRunResults(runId, showCalculatedTotals);
	const [rows, setRows] = useState<EditableRosterRow[]>([]);
	const [search, setSearch] = useState("");
	const [dirty, setDirty] = useState(false);
	const deferredSearch = useDeferredValue(search.trim().toLowerCase());
	const [columnVisibility, setColumnVisibility] = usePersistedColumnVisibility(
		"accord:pay-run-roster:columns",
		{ sevarth_id: false },
	);

	useEffect(() => {
		if (!rosterQuery.data || dirty) return;
		setRows(toEditableRows(rosterQuery.data));
	}, [dirty, rosterQuery.data]);

	useEffect(() => {
		onDirtyChange(dirty);
	}, [dirty, onDirtyChange]);

	const visibleRows = useMemo(() => {
		if (!deferredSearch) return rows;
		return rows.filter((row) =>
			`${row.employee_number} ${row.employee_name ?? ""} ${row.sevarth_id ?? ""}`
				.toLowerCase()
				.includes(deferredSearch),
		);
	}, [deferredSearch, rows]);

	const selectedCount = rows.reduce((count, row) => count + (row.selected ? 1 : 0), 0);
	const allSelected = rows.length > 0 && selectedCount === rows.length;

	const updateRow = useCallback(
		(employeeId: string, update: (row: EditableRosterRow) => EditableRosterRow) => {
			setRows((current) =>
				current.map((row) => (row.employee_id === employeeId ? update(row) : row)),
			);
			setDirty(true);
		},
		[],
	);

	const updateField = useCallback(
		(employeeId: string, field: EditableField, value: string) => {
			updateRow(employeeId, (row) => ({ ...row, selected: true, [field]: value }));
		},
		[updateRow],
	);

	const setAllSelected = useCallback((selected: boolean) => {
		setRows((current) => current.map((row) => ({ ...row, selected })));
		setDirty(true);
	}, []);

	const periodDays = daysInPeriod(periodYear, periodMonth);
	const netPayableByEmployeeId = useMemo(() => {
		if (!showCalculatedTotals || !resultsQuery.data) return null;
		return new Map(
			resultsQuery.data.employees.map((employee) => [employee.employee_id, employee.net_payable]),
		);
	}, [resultsQuery.data, showCalculatedTotals]);

	const columns = useMemo(
		() =>
			buildRosterColumns({
				editable: editable && editing,
				periodDays,
				netPayableByEmployeeId,
				allSelected,
				setAllSelected,
				updateRow,
				updateField,
			}),
		[
			allSelected,
			editable,
			editing,
			netPayableByEmployeeId,
			periodDays,
			setAllSelected,
			updateField,
			updateRow,
		],
	);

	const table = useReactTable({
		data: visibleRows,
		columns,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => row.employee_id,
		state: { columnVisibility },
		onColumnVisibilityChange: setColumnVisibility,
	});

	const handleSave = useCallback(async (): Promise<boolean> => {
		const selectedRows = rows.filter((row) => row.selected);
		if (selectedRows.length === 0) {
			toast.error("Select at least one employee for this pay run.");
			return false;
		}
		try {
			const saved = await replaceRoster.mutateAsync({
				employees: selectedRows.map((row) => ({
					employee_id: row.employee_id,
					payable_days: row.payable_days.trim(),
					da_percent: optionalDecimal(row.da_percent),
					da_difference: optionalDecimal(row.da_difference),
					hra_percent: optionalDecimal(row.hra_percent),
					transport_amount: optionalDecimal(row.transport_amount),
				})),
			});
			setRows(toEditableRows(saved));
			setDirty(false);
			toast.success(`Saved ${saved.filter((row) => row.selected).length} employees`);
			return true;
		} catch (error) {
			toast.error(getErrorMessage(error, "Failed to save payroll employees."));
			return false;
		}
	}, [replaceRoster, rows]);

	const handleCancel = useCallback(() => {
		setRows(toEditableRows(rosterQuery.data ?? []));
		setDirty(false);
	}, [rosterQuery.data]);

	useImperativeHandle(
		ref,
		() => ({
			cancel: handleCancel,
			save: handleSave,
		}),
		[handleCancel, handleSave],
	);

	if (rosterQuery.isLoading) {
		return <Skeleton className="h-72 w-full" />;
	}

	if (rosterQuery.isError) {
		return (
			<ErrorWithRetry
				message={getErrorMessage(rosterQuery.error, "Failed to load payroll employees.")}
				onRetry={() => void rosterQuery.refetch()}
			/>
		);
	}

	return (
		<div className="grid gap-3" data-testid="payroll-run-roster">
			<PageToolbar>
				<DataSearchControl
					search={search || undefined}
					title="Search Payroll Employees"
					placeholder="Search employees"
					onSearchChange={(value) => setSearch(value ?? "")}
				/>
			</PageToolbar>

			{visibleRows.length === 0 ? (
				<p className="text-sm text-muted-foreground">No employees found.</p>
			) : (
				<DataTableShell table={table} tableClassName="min-w-[70rem]" />
			)}
		</div>
	);
});
