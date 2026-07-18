import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import type {
	PayrollRunValidateResult,
	ValidationFinding,
	ValidationFindingSeverity,
} from "@/lib/api/payroll-runs";

const SEVERITY_ORDER: ValidationFindingSeverity[] = ["error", "warning", "info"];

const SEVERITY_LABELS: Record<ValidationFindingSeverity, string> = {
	error: "Errors",
	warning: "Warnings",
	info: "Info",
};

function groupBySeverity(
	findings: ValidationFinding[],
): Record<ValidationFindingSeverity, ValidationFinding[]> {
	const groups: Record<ValidationFindingSeverity, ValidationFinding[]> = {
		error: [],
		warning: [],
		info: [],
	};
	for (const finding of findings) {
		const severity = SEVERITY_ORDER.includes(finding.severity) ? finding.severity : "info";
		groups[severity].push(finding);
	}
	return groups;
}

function FindingRow({ finding }: { finding: ValidationFinding }) {
	const contextParts = [
		finding.employee_ref ? `Employee ${finding.employee_ref}` : null,
		finding.component_code ? `Component ${finding.component_code}` : null,
	].filter(Boolean);

	const accent =
		finding.severity === "error"
			? "border-l-destructive bg-destructive/5"
			: finding.severity === "warning"
				? "border-l-amber-500 bg-amber-500/5"
				: "border-l-border bg-muted/30";

	return (
		<li
			className={`rounded-md border border-border/60 border-l-4 px-3 py-2 ${accent}`}
			data-testid={`finding-${finding.severity}-${finding.code}`}
		>
			<div className="flex flex-wrap items-center gap-2">
				<Badge
					variant={
						finding.severity === "error"
							? "destructive"
							: finding.severity === "warning"
								? "warning"
								: "muted"
					}
				>
					{finding.severity}
				</Badge>
				<span className="font-mono text-xs text-muted-foreground">{finding.code}</span>
			</div>
			<p className="mt-1 text-sm text-foreground">{finding.message}</p>
			{contextParts.length > 0 ? (
				<p className="mt-1 text-xs text-muted-foreground">{contextParts.join(" · ")}</p>
			) : null}
		</li>
	);
}

type ValidationFindingsPanelProps = {
	result: PayrollRunValidateResult;
};

export function ValidationFindingsPanel({ result }: ValidationFindingsPanelProps) {
	const groups = groupBySeverity(result.findings);
	const hasErrors = result.blocking || groups.error.length > 0;

	return (
		<section className="grid gap-3" data-testid="validation-findings-panel">
			<div className="flex flex-wrap items-center gap-2">
				<h3 className="text-sm font-medium">Validation Findings</h3>
				{result.findings.length === 0 ? (
					<Badge variant="success">No issues</Badge>
				) : (
					<Badge variant="outline">{result.findings.length} finding(s)</Badge>
				)}
			</div>

			{hasErrors ? (
				<Alert variant="destructive" data-testid="validation-blocking-banner">
					<AlertTitle>Blocking validation errors</AlertTitle>
					<AlertDescription>
						This run has error-level findings and cannot be submitted until they are resolved.
					</AlertDescription>
				</Alert>
			) : null}

			{result.findings.length === 0 ? (
				<p className="text-sm text-muted-foreground">Validation completed with no findings.</p>
			) : (
				SEVERITY_ORDER.map((severity) => {
					const items = groups[severity];
					if (items.length === 0) return null;
					return (
						<div key={severity} className="grid gap-2" data-testid={`findings-group-${severity}`}>
							<div className="flex items-center gap-2">
								<span
									className={
										severity === "error"
											? "text-sm font-medium text-destructive"
											: severity === "warning"
												? "text-sm font-medium text-amber-600 dark:text-amber-500"
												: "text-sm font-medium text-muted-foreground"
									}
								>
									{SEVERITY_LABELS[severity]}
								</span>
								<Badge variant="outline">{items.length}</Badge>
							</div>
							<ul className="grid gap-2">
								{items.map((finding) => (
									<FindingRow
										key={`${finding.severity}:${finding.code}:${finding.employee_ref ?? ""}:${finding.component_code ?? ""}:${finding.message}`}
										finding={finding}
									/>
								))}
							</ul>
						</div>
					);
				})
			)}
		</section>
	);
}
