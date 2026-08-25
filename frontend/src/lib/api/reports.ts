import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchDownload, fetchJson, jsonRequest } from "@/lib/api/http";
import { buildQueryString, shouldSetQueryParam } from "@/lib/api/query-utils";
import { downloadBlob } from "@/lib/download";
import type { components } from "@/types/api.generated";

/**
 * Report endpoints and schemas are available in `api.generated.ts`.
 * Local types add UI-specific constraints or detail, or provide module-level names.
 */
export type ReportFormat = "excel" | "pdf" | "json";

export type ReportCatalogEntry = Omit<components["schemas"]["ReportTypeItem"], "formats"> & {
	formats: ReportFormat[];
};

export type ReportCatalogResponse = Omit<
	components["schemas"]["ReportTypeListResponse"],
	"items"
> & {
	items: ReportCatalogEntry[];
};

export type GenerateReportRequest = Omit<
	components["schemas"]["GenerateReportRequest"],
	"format"
> & {
	format: ReportFormat;
};

export type ExportReportsRequest = components["schemas"]["ExportReportsRequest"];
export type ExportReportsResponse = components["schemas"]["ExportReportsResponse"];

export type ReportJobStatus =
	| "queued"
	| "running"
	| "succeeded"
	| "failed"
	| "dead_letter"
	| "cancelled";

export type ReportJobResponse = Omit<
	components["schemas"]["ReportJobResponse"],
	"result" | "status"
> & {
	status: ReportJobStatus;
	result?: { artifact_id?: string; reused?: boolean; filename?: string } | null;
};

export type ReportPreviewColumn = {
	key: string;
	header: string;
	kind: string;
};

export type ReportPreviewSection = {
	title: string;
	columns: ReportPreviewColumn[];
	rows: Record<string, string | number | null>[];
	totals?: Record<string, string | number | null>;
};

export type ReportPreviewResponse = Omit<
	components["schemas"]["ReportPreviewResponse"],
	"sections"
> & {
	sections: ReportPreviewSection[];
};

export type ArtifactResponse = components["schemas"]["ArtifactResponse"];
export type PaginatedArtifactResponse =
	components["schemas"]["PaginatedResponse_ArtifactResponse_"];

export type ListArtifactsParams = {
	report_type?: string | null;
	posted_run_id?: string | null;
	status?: string | null;
	page?: number;
	page_size?: number;
};

export const REPORT_JOB_POLL_INTERVAL_MS = 1500;

export const reportQueryKeys = {
	job: (jobId: string) => ["reports", "job", jobId] as const,
	preview: (reportType: string, postedRunId: string) =>
		["reports", "preview", reportType, postedRunId] as const,
	artifacts: () => ["artifacts"] as const,
	artifactList: (params: ListArtifactsParams) => ["artifacts", "list", params] as const,
};

export function isActiveJobStatus(status: ReportJobStatus | undefined): boolean {
	return status === "queued" || status === "running";
}

export function jobArtifactId(job: ReportJobResponse | undefined): string | undefined {
	return job?.result?.artifact_id;
}

export function jobErrorMessage(job: ReportJobResponse | undefined): string | undefined {
	return job?.last_error ?? undefined;
}

export function getReportPreview(reportType: string, postedRunId: string) {
	const qs = buildQueryString({ posted_run_id: postedRunId }, shouldSetQueryParam);
	return fetchJson<ReportPreviewResponse>(`/api/reports/${reportType}/preview${qs}`);
}

export function exportReports(body: ExportReportsRequest) {
	return fetchJson<ExportReportsResponse>("/api/reports/export", jsonRequest("POST", body));
}

export function getReportJob(jobId: string) {
	return fetchJson<ReportJobResponse>(`/api/reports/jobs/${jobId}`);
}

export function listArtifacts(params: ListArtifactsParams = {}) {
	const qs = buildQueryString(
		{
			report_type: params.report_type,
			posted_run_id: params.posted_run_id,
			status: params.status,
			page: params.page,
			page_size: params.page_size,
		},
		shouldSetQueryParam,
	);
	return fetchJson<PaginatedArtifactResponse>(`/api/artifacts${qs}`);
}

export async function downloadArtifact(
	artifactId: string,
	fallbackFilename = "report",
	options?: { preferFilename?: string },
) {
	const { blob, filename } = await fetchDownload(
		`/api/artifacts/${artifactId}/download`,
		undefined,
		fallbackFilename,
	);
	downloadBlob(blob, options?.preferFilename?.trim() || filename);
}

export function useReportPreview(reportType: string | undefined, postedRunId: string | null) {
	return useQuery({
		queryKey: reportQueryKeys.preview(reportType ?? "", postedRunId ?? ""),
		queryFn: () => getReportPreview(reportType!, postedRunId!),
		enabled: Boolean(reportType && postedRunId),
	});
}

export function useReportJob(jobId: string | undefined) {
	return useQuery({
		queryKey: reportQueryKeys.job(jobId ?? ""),
		queryFn: () => getReportJob(jobId!),
		enabled: Boolean(jobId),
		refetchInterval: (query) => {
			const status = query.state.data?.status;
			if (isActiveJobStatus(status)) return REPORT_JOB_POLL_INTERVAL_MS;
			return false;
		},
	});
}

export function useArtifactsList(params: ListArtifactsParams = {}) {
	return useQuery({
		queryKey: reportQueryKeys.artifactList(params),
		queryFn: () => listArtifacts(params),
		placeholderData: (previous) => previous,
	});
}

export function useExportReports() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: exportReports,
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: reportQueryKeys.artifacts() });
		},
	});
}

export function useDownloadArtifact() {
	return useMutation({
		mutationFn: (input: string | { artifactId: string; preferFilename?: string }) => {
			if (typeof input === "string") {
				return downloadArtifact(input);
			}
			return downloadArtifact(input.artifactId, "report", {
				preferFilename: input.preferFilename,
			});
		},
	});
}
