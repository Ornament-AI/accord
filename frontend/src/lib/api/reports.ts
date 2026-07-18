import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchDownload, fetchJson } from "@/lib/api/http";
import { shouldSetQueryParam } from "@/lib/api/query-utils";
import { downloadBlob } from "@/lib/download";
import type { components } from "@/types/api.generated";

/**
 * Report generation / job types are defined locally until OpenAPI catches up.
 * Divergence to reconcile at integration: `api.generated.ts` currently exposes
 * artifacts + report-configurations only — not GET/POST /api/reports* job APIs.
 */
export type ReportFormat = "excel" | "pdf" | "json";

export type ReportCatalogEntry = {
	report_type: string;
	title?: string;
	formats: ReportFormat[];
	template_version: string;
};

export type ReportCatalogResponse = {
	report_types: ReportCatalogEntry[];
};

export type GenerateReportRequest = {
	report_type: string;
	posted_run_id: string;
	format: ReportFormat;
};

export type GenerateReportResponse = {
	job_id: string;
	status: string;
};

export type ReportJobStatus =
	| "queued"
	| "running"
	| "succeeded"
	| "failed"
	| "dead_letter"
	| "cancelled";

export type ReportJobResponse = {
	job_id: string;
	status: ReportJobStatus;
	artifact_id?: string;
	error?: string;
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
	all: () => ["reports"] as const,
	catalog: () => ["reports", "catalog"] as const,
	job: (jobId: string) => ["reports", "job", jobId] as const,
	artifacts: () => ["artifacts"] as const,
	artifactList: (params: ListArtifactsParams) => ["artifacts", "list", params] as const,
};

function buildQueryString(
	params: Record<string, string | number | boolean | null | undefined>,
): string {
	const search = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (!shouldSetQueryParam(key, value)) continue;
		search.set(key, String(value));
	}
	const qs = search.toString();
	return qs ? `?${qs}` : "";
}

export function isActiveJobStatus(status: ReportJobStatus | undefined): boolean {
	return status === "queued" || status === "running";
}

export function isTerminalJobStatus(status: ReportJobStatus | undefined): boolean {
	return (
		status === "succeeded" ||
		status === "failed" ||
		status === "dead_letter" ||
		status === "cancelled"
	);
}

export function listReportCatalog() {
	return fetchJson<ReportCatalogResponse>("/api/reports");
}

export function generateReport(body: GenerateReportRequest) {
	return fetchJson<GenerateReportResponse>("/api/reports/generate", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function getReportJob(jobId: string) {
	return fetchJson<ReportJobResponse>(`/api/reports/jobs/${jobId}`);
}

export function listArtifacts(params: ListArtifactsParams = {}) {
	const qs = buildQueryString({
		report_type: params.report_type,
		posted_run_id: params.posted_run_id,
		status: params.status,
		page: params.page,
		page_size: params.page_size,
	});
	return fetchJson<PaginatedArtifactResponse>(`/api/artifacts${qs}`);
}

export async function downloadArtifact(artifactId: string, fallbackFilename = "report") {
	const { blob, filename } = await fetchDownload(
		`/api/artifacts/${artifactId}/download`,
		undefined,
		fallbackFilename,
	);
	downloadBlob(blob, filename);
}

export function useReportCatalog() {
	return useQuery({
		queryKey: reportQueryKeys.catalog(),
		queryFn: listReportCatalog,
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

export function useGenerateReport() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: generateReport,
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: reportQueryKeys.artifacts() });
		},
	});
}

export function useDownloadArtifact() {
	return useMutation({
		mutationFn: (artifactId: string) => downloadArtifact(artifactId),
	});
}
