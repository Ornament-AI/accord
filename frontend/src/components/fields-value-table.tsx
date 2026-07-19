import type { ReactNode } from "react";

import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";

export type FieldsValueRow = {
	label: ReactNode;
	value: ReactNode;
	valueTestId?: string;
};

type FieldsValueTableProps = {
	rows: FieldsValueRow[];
};

/** Compact two-column Field | Value table; Value column is right-aligned. */
export function FieldsValueTable({ rows }: FieldsValueTableProps) {
	return (
		<Table surface={false}>
			<TableHeader>
				<TableRow>
					<TableHead className="w-44 min-w-40">Field</TableHead>
					<TableHead className="text-right">Value</TableHead>
				</TableRow>
			</TableHeader>
			<TableBody>
				{rows.map((row, index) => (
					<TableRow key={typeof row.label === "string" ? row.label : index}>
						<TableCell className="text-muted-foreground">{row.label}</TableCell>
						<TableCell className="text-right" data-testid={row.valueTestId}>
							{row.value}
						</TableCell>
					</TableRow>
				))}
			</TableBody>
		</Table>
	);
}
