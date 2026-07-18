import { HttpResponse, http } from "msw";

import type {
	ArtifactResponse,
	GenerateReportRequest,
	ReportCatalogEntry,
	ReportCatalogResponse,
	ReportJobResponse,
	ReportJobStatus,
} from "@/lib/api/reports";

export type ReportHandlersOptions = {
	catalog?: ReportCatalogEntry[];
	artifacts?: ArtifactResponse[];
	/** Ordered statuses returned by successive GET /api/reports/jobs/:id polls. */
	jobStatusSequence?: ReportJobStatus[];
	/** Error message when the terminal status is failed/dead_letter. */
	jobError?: string;
	generateError?: { status: number; body: Record<string, unknown> };
	onGenerate?: (body: GenerateReportRequest) => void;
};

export function buildCatalogEntry(
	overrides: Partial<ReportCatalogEntry> & { report_type: string },
): ReportCatalogEntry {
	return {
		report_type: overrides.report_type,
		title: overrides.title,
		formats: overrides.formats ?? ["excel", "pdf", "json"],
		template_version: overrides.template_version ?? "2026.1",
	};
}

export function buildArtifact(
	overrides: Partial<ArtifactResponse> & { id: string; report_type: string },
): ArtifactResponse {
	const now = "2026-07-18T10:00:00Z";
	return {
		id: overrides.id,
		organization_id: overrides.organization_id ?? "00000000-0000-4000-8000-000000000001",
		report_type: overrides.report_type,
		posted_run_id: overrides.posted_run_id ?? null,
		status: overrides.status ?? "ready",
		template_version: overrides.template_version ?? "2026.1",
		content_type:
			overrides.content_type ?? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		size_bytes: overrides.size_bytes ?? 12_345,
		checksum_sha256:
			overrides.checksum_sha256 ??
			"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
		requested_by: overrides.requested_by ?? "00000000-0000-4000-8000-000000000099",
		engine_version: overrides.engine_version ?? "1.0.0",
		object_version: overrides.object_version ?? null,
		retention_expires_at: overrides.retention_expires_at ?? null,
		created_at: overrides.created_at ?? now,
		updated_at: overrides.updated_at ?? now,
	};
}

export function defaultReportCatalog(): ReportCatalogEntry[] {
	return [
		buildCatalogEntry({
			report_type: "payroll_register.pay_bill",
			title: "Pay Bill",
		}),
		buildCatalogEntry({
			report_type: "payroll_register.treasury_face",
			title: "Treasury Face",
		}),
		buildCatalogEntry({
			report_type: "payments.bank_rtgs_advice",
			title: "Bank RTGS Advice",
		}),
		buildCatalogEntry({
			report_type: "retirement.gpf_mumbai",
			title: "GPF Mumbai Schedule",
			formats: ["excel", "pdf"],
		}),
		buildCatalogEntry({
			report_type: "statutory.income_tax",
			title: "Income Tax Schedule",
		}),
		buildCatalogEntry({
			report_type: "recovery.hba",
			title: "HBA Schedule",
		}),
		buildCatalogEntry({
			report_type: "accommodation.mumbai",
			title: "Accommodation — Mumbai",
		}),
		buildCatalogEntry({
			report_type: "approval.office_note",
			title: "Office Approval Note",
		}),
	];
}

export function createReportHandlers(options: ReportHandlersOptions = {}) {
	const catalog: ReportCatalogResponse = {
		report_types: options.catalog ?? defaultReportCatalog(),
	};
	const artifacts = new Map<string, ArtifactResponse>();
	for (const artifact of options.artifacts ?? []) {
		artifacts.set(artifact.id, artifact);
	}

	const jobs = new Map<
		string,
		{
			pollCount: number;
			request: GenerateReportRequest;
			artifactId?: string;
		}
	>();
	const statusSequence = options.jobStatusSequence ?? ["queued", "running", "succeeded"];
	let jobCounter = 0;

	return {
		handlers: [
			http.get("/api/reports", () => HttpResponse.json(catalog)),

			http.post("/api/reports/generate", async ({ request }) => {
				if (options.generateError) {
					return HttpResponse.json(options.generateError.body, {
						status: options.generateError.status,
					});
				}
				const body = (await request.json()) as GenerateReportRequest;
				options.onGenerate?.(body);
				jobCounter += 1;
				const jobId = `job-${jobCounter}`;
				jobs.set(jobId, { pollCount: 0, request: body });
				return HttpResponse.json({ job_id: jobId, status: "queued" }, { status: 202 });
			}),

			http.get("/api/reports/jobs/:jobId", ({ params }) => {
				const jobId = String(params.jobId);
				const job = jobs.get(jobId);
				if (!job) {
					return HttpResponse.json({ detail: "Job not found", error: "NotFound" }, { status: 404 });
				}

				const index = Math.min(job.pollCount, statusSequence.length - 1);
				job.pollCount += 1;
				const status = statusSequence[index] ?? "succeeded";

				const response: ReportJobResponse = {
					job_id: jobId,
					status,
				};

				if (status === "succeeded") {
					if (!job.artifactId) {
						const artifactId = `artifact-from-${jobId}`;
						job.artifactId = artifactId;
						const created = buildArtifact({
							id: artifactId,
							report_type: job.request.report_type,
							posted_run_id: job.request.posted_run_id,
							content_type:
								job.request.format === "pdf"
									? "application/pdf"
									: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
							size_bytes: 4_096,
							created_at: "2026-07-18T12:00:00Z",
							updated_at: "2026-07-18T12:00:00Z",
						});
						artifacts.set(artifactId, created);
					}
					response.artifact_id = job.artifactId;
				}

				if (status === "failed" || status === "dead_letter") {
					response.error = options.jobError ?? "Renderer exploded";
				}

				return HttpResponse.json(response);
			}),

			http.get("/api/artifacts", ({ request }) => {
				const url = new URL(request.url);
				const reportType = url.searchParams.get("report_type");
				const postedRunId = url.searchParams.get("posted_run_id");
				const status = url.searchParams.get("status");
				const page = Number(url.searchParams.get("page") ?? "1");
				const pageSize = Number(url.searchParams.get("page_size") ?? "20");

				let items = Array.from(artifacts.values());
				if (reportType) items = items.filter((item) => item.report_type === reportType);
				if (postedRunId) items = items.filter((item) => item.posted_run_id === postedRunId);
				if (status) items = items.filter((item) => item.status === status);
				items.sort((a, b) => b.created_at.localeCompare(a.created_at));

				const total = items.length;
				const totalPages = Math.max(1, Math.ceil(total / pageSize) || 1);
				const start = (page - 1) * pageSize;
				const pageItems = items.slice(start, start + pageSize);

				return HttpResponse.json({
					items: pageItems,
					page,
					page_size: pageSize,
					total,
					total_pages: totalPages,
				});
			}),

			http.get("/api/artifacts/:artifactId/download", ({ params }) => {
				const artifactId = String(params.artifactId);
				const artifact = artifacts.get(artifactId);
				if (!artifact) {
					return HttpResponse.json(
						{ detail: "Artifact not found", error: "NotFound" },
						{ status: 404 },
					);
				}
				const body = new Uint8Array([80, 75, 3, 4]); // ZIP/XLSX magic-ish
				return new HttpResponse(body, {
					status: 200,
					headers: {
						"Content-Type": artifact.content_type,
						"Content-Disposition": `attachment; filename="${artifact.report_type}.xlsx"`,
					},
				});
			}),
		],
		artifacts,
		jobs,
	};
}
