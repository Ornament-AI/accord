import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import {
	type GenerateReportRequest,
	type ReportFormat,
	reportQueryKeys,
	useDownloadArtifact,
	useGenerateReport,
	useReportJob,
} from "@/lib/api/reports";

import { generationSlotKey } from "./report-families";

export type GenerationSlot = {
	jobId: string;
	reportType: string;
	format: ReportFormat;
	postedRunId: string;
};

/**
 * Tracks in-flight report generation jobs keyed by report_type:format.
 * Extracted for testability of start / retry flows.
 */
export function useReportGeneration() {
	const [slots, setSlots] = useState<Record<string, GenerationSlot>>({});
	const [pendingKey, setPendingKey] = useState<string | null>(null);
	const [lastAttemptKey, setLastAttemptKey] = useState<string | null>(null);
	const generateMutation = useGenerateReport();

	const start = useCallback(
		async (input: GenerateReportRequest) => {
			const key = generationSlotKey(input.report_type, input.format);
			setPendingKey(key);
			setLastAttemptKey(key);
			try {
				const result = await generateMutation.mutateAsync(input);
				setSlots((prev) => ({
					...prev,
					[key]: {
						jobId: result.job_id,
						reportType: input.report_type,
						format: input.format,
						postedRunId: input.posted_run_id,
					},
				}));
				return result;
			} finally {
				setPendingKey(null);
			}
		},
		[generateMutation],
	);

	const retry = useCallback(
		async (slot: GenerationSlot) => {
			return start({
				report_type: slot.reportType,
				posted_run_id: slot.postedRunId,
				format: slot.format,
			});
		},
		[start],
	);

	return {
		slots,
		pendingKey,
		lastAttemptKey,
		isStarting: generateMutation.isPending,
		startError: generateMutation.error,
		start,
		retry,
	};
}

export type ReportGenerationController = ReturnType<typeof useReportGeneration>;

/** Polls a single job and exposes download / retry actions for that slot. */
export function useGenerationJobStatus(slot: GenerationSlot | undefined) {
	const queryClient = useQueryClient();
	const jobQuery = useReportJob(slot?.jobId);
	const downloadMutation = useDownloadArtifact();

	useEffect(() => {
		if (jobQuery.data?.status === "succeeded") {
			void queryClient.invalidateQueries({ queryKey: reportQueryKeys.artifacts() });
		}
	}, [jobQuery.data?.status, queryClient]);

	const download = useCallback(async () => {
		const artifactId = jobQuery.data?.artifact_id;
		if (!artifactId) return;
		await downloadMutation.mutateAsync(artifactId);
	}, [downloadMutation, jobQuery.data?.artifact_id]);

	return {
		job: jobQuery.data,
		isLoading: jobQuery.isLoading,
		isError: jobQuery.isError,
		error: jobQuery.error,
		download,
		isDownloading: downloadMutation.isPending,
	};
}
