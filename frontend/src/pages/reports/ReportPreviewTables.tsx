import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import type { ReportPreviewResponse, ReportPreviewSection } from "@/lib/api/reports";

function cellText(value: string | number | null | undefined): string {
	if (value === null || value === undefined || value === "") return "—";
	return String(value);
}

function PreviewSectionTable({ section }: { section: ReportPreviewSection }) {
	const columns = section.columns ?? [];
	const rows = section.rows ?? [];
	const totals = section.totals;

	return (
		<div className="flex flex-col gap-2" data-testid={`preview-section-${section.title}`}>
			<h3 className="text-sm font-semibold tracking-tight">{section.title}</h3>
			<div className="overflow-x-auto rounded-md border">
				<Table>
					<TableHeader>
						<TableRow>
							{columns.map((column) => (
								<TableHead key={column.key}>{column.header}</TableHead>
							))}
						</TableRow>
					</TableHeader>
					<TableBody>
						{rows.length === 0 ? (
							<TableRow>
								<TableCell colSpan={Math.max(columns.length, 1)} className="text-muted-foreground">
									No rows for this section.
								</TableCell>
							</TableRow>
						) : (
							rows.map((row) => (
								<TableRow key={columns.map((column) => cellText(row[column.key])).join("\u0001")}>
									{columns.map((column) => (
										<TableCell
											key={column.key}
											className={column.kind === "money" ? "tabular-nums" : undefined}
										>
											{cellText(row[column.key])}
										</TableCell>
									))}
								</TableRow>
							))
						)}
						{totals ? (
							<TableRow className="font-medium">
								{columns.map((column) => (
									<TableCell
										key={column.key}
										className={column.kind === "money" ? "tabular-nums" : undefined}
									>
										{cellText(totals[column.key])}
									</TableCell>
								))}
							</TableRow>
						) : null}
					</TableBody>
				</Table>
			</div>
		</div>
	);
}

export function ReportPreviewTables({ preview }: { preview: ReportPreviewResponse }) {
	return (
		<div className="flex flex-col gap-6" data-testid="report-preview-tables">
			<div>
				<h2 className="text-base font-semibold tracking-tight">{preview.title}</h2>
				<p className="text-muted-foreground text-sm">
					{preview.organization_name}
					{preview.subtitle ? ` · ${preview.subtitle}` : ""}
				</p>
			</div>
			{preview.sections.map((section) => (
				<PreviewSectionTable key={section.title} section={section} />
			))}
		</div>
	);
}
