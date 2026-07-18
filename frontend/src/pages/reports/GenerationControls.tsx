import { Download, Loader2, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { isActiveJobStatus, type ReportCatalogEntry } from "@/lib/api/reports";
import { getErrorMessage } from "@/lib/errors";

import { availableUiFormats, formatButtonLabel, generationSlotKey } from "./report-families";
import {
	type GenerationSlot,
	type ReportGenerationController,
	useGenerationJobStatus,
} from "./use-report-generation";

type GenerationControlsProps = {
	entry: ReportCatalogEntry;
	postedRunId: string | null;
	disabled?: boolean;
	generation: ReportGenerationController;
};

function SlotStatus({
	slot,
	onRetry,
	isRetrying,
}: {
	slot: GenerationSlot;
	onRetry: () => void;
	isRetrying: boolean;
}) {
	const { job, isLoading, download, isDownloading } = useGenerationJobStatus(slot);

	if (isLoading && !job) {
		return (
			<span className="text-muted-foreground inline-flex items-center gap-1 text-xs" role="status">
				<Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
				Starting…
			</span>
		);
	}

	if (!job) return null;

	if (isActiveJobStatus(job.status)) {
		const label = job.status === "queued" ? "Queued…" : "Generating…";
		return (
			<span
				className="text-muted-foreground inline-flex items-center gap-1 text-xs"
				role="status"
				data-testid={`job-status-${slot.jobId}`}
			>
				<Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
				{label}
			</span>
		);
	}

	if (job.status === "succeeded" && job.artifact_id) {
		return (
			<Button
				type="button"
				size="sm"
				variant="secondary"
				onClick={() => void download()}
				disabled={isDownloading}
				data-testid={`download-job-${slot.jobId}`}
			>
				{isDownloading ? (
					<Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
				) : (
					<Download className="size-3.5" aria-hidden="true" />
				)}
				Download
			</Button>
		);
	}

	if (job.status === "failed" || job.status === "dead_letter") {
		return (
			<div className="flex flex-wrap items-center gap-2" data-testid={`job-failed-${slot.jobId}`}>
				<span className="text-destructive text-xs" role="alert">
					{job.error?.trim() || "Report generation failed."}
				</span>
				<Button type="button" size="sm" variant="outline" onClick={onRetry} disabled={isRetrying}>
					<RotateCcw className="size-3.5" aria-hidden="true" />
					Retry
				</Button>
			</div>
		);
	}

	if (job.status === "cancelled") {
		return (
			<span className="text-muted-foreground text-xs" role="status">
				Cancelled
			</span>
		);
	}

	return null;
}

export function GenerationControls({
	entry,
	postedRunId,
	disabled = false,
	generation,
}: GenerationControlsProps) {
	const formats = availableUiFormats(entry);
	const canGenerate = Boolean(postedRunId) && !disabled;

	return (
		<div className="flex flex-col gap-2">
			<div className="flex flex-wrap items-center gap-2">
				{formats.map((format) => {
					const key = generationSlotKey(entry.report_type, format);
					const slot = generation.slots[key];
					const isPending = generation.pendingKey === key;
					return (
						<div key={key} className="flex flex-wrap items-center gap-2">
							{!slot ? (
								<Button
									type="button"
									size="sm"
									variant="outline"
									disabled={!canGenerate || isPending || generation.isStarting}
									aria-label={`Generate ${formatButtonLabel(format)} for ${entry.report_type}`}
									onClick={() => {
										if (!postedRunId) return;
										void generation.start({
											report_type: entry.report_type,
											posted_run_id: postedRunId,
											format,
										});
									}}
								>
									{isPending ? (
										<Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
									) : null}
									{formatButtonLabel(format)}
								</Button>
							) : (
								<>
									<span className="text-muted-foreground text-xs font-medium">
										{formatButtonLabel(format)}
									</span>
									<SlotStatus
										slot={slot}
										isRetrying={generation.pendingKey === key}
										onRetry={() => {
											void generation.retry(slot);
										}}
									/>
								</>
							)}
						</div>
					);
				})}
			</div>
			{generation.startError &&
			generation.pendingKey === null &&
			generation.lastAttemptKey?.startsWith(`${entry.report_type}:`) ? (
				<p className="text-destructive text-xs" role="alert">
					{getErrorMessage(generation.startError, "Failed to start report generation.")}
				</p>
			) : null}
		</div>
	);
}
