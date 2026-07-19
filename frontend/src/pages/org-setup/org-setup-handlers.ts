import { HttpResponse, http } from "msw";

import type {
	EmployeeGroupCreate,
	EmployeeGroupResponse,
	EmployeeGroupUpdate,
	OfficeCreate,
	OfficeResponse,
	OfficeUpdate,
	PayrollUnitCreate,
	PayrollUnitResponse,
	PayrollUnitUpdate,
	PostCreate,
	PostResponse,
	PostUpdate,
} from "@/lib/api/org-structure";

export type OrgSetupHandlersOptions = {
	offices?: OfficeResponse[];
	payrollUnits?: PayrollUnitResponse[];
	posts?: PostResponse[];
	employeeGroups?: EmployeeGroupResponse[];
	/** When set, POST create endpoints return this status/body (e.g. 409). */
	createError?: { status: number; body: Record<string, unknown> };
};

const NOW = "2026-01-15T10:00:00Z";

export function buildOffice(
	overrides: Partial<OfficeResponse> & Pick<OfficeResponse, "id" | "code">,
): OfficeResponse {
	return {
		id: overrides.id,
		code: overrides.code,
		name: overrides.name ?? `Office ${overrides.code}`,
		jurisdiction: overrides.jurisdiction ?? "mumbai",
		created_at: overrides.created_at ?? NOW,
		updated_at: overrides.updated_at ?? NOW,
	};
}

export function buildPayrollUnit(
	overrides: Partial<PayrollUnitResponse> & Pick<PayrollUnitResponse, "id" | "code">,
): PayrollUnitResponse {
	return {
		id: overrides.id,
		code: overrides.code,
		name: overrides.name ?? `Payroll unit ${overrides.code}`,
		created_at: overrides.created_at ?? NOW,
		updated_at: overrides.updated_at ?? NOW,
	};
}

export function buildPost(
	overrides: Partial<PostResponse> & Pick<PostResponse, "id" | "designation">,
): PostResponse {
	return {
		id: overrides.id,
		designation: overrides.designation,
		class_name: overrides.class_name ?? "Class I",
		created_at: overrides.created_at ?? NOW,
		updated_at: overrides.updated_at ?? NOW,
	};
}

export function buildEmployeeGroup(
	overrides: Partial<EmployeeGroupResponse> & Pick<EmployeeGroupResponse, "id" | "code">,
): EmployeeGroupResponse {
	return {
		id: overrides.id,
		code: overrides.code,
		name: overrides.name ?? `Group ${overrides.code}`,
		created_at: overrides.created_at ?? NOW,
		updated_at: overrides.updated_at ?? NOW,
	};
}

export function createOrgSetupHandlers(options: OrgSetupHandlersOptions = {}) {
	const offices = new Map<string, OfficeResponse>();
	const payrollUnits = new Map<string, PayrollUnitResponse>();
	const posts = new Map<string, PostResponse>();
	const employeeGroups = new Map<string, EmployeeGroupResponse>();

	const seedOffices = options.offices ?? [
		buildOffice({ id: "office-1", code: "HO", name: "Head Office", jurisdiction: "mumbai" }),
		buildOffice({
			id: "office-2",
			code: "RO-NAG",
			name: "Nagpur Regional",
			jurisdiction: "nagpur",
		}),
	];
	for (const office of seedOffices) offices.set(office.id, office);

	const seedPayrollUnits = options.payrollUnits ?? [
		buildPayrollUnit({ id: "pu-1", code: "PU-HQ", name: "HQ Payroll" }),
		buildPayrollUnit({ id: "pu-2", code: "PU-REG", name: "Regional Payroll" }),
	];
	for (const unit of seedPayrollUnits) payrollUnits.set(unit.id, unit);

	const seedPosts = options.posts ?? [
		buildPost({ id: "post-1", designation: "Clerk", class_name: "Class III" }),
		buildPost({ id: "post-2", designation: "Officer", class_name: "Class I" }),
	];
	for (const post of seedPosts) posts.set(post.id, post);

	const seedGroups = options.employeeGroups ?? [
		buildEmployeeGroup({ id: "eg-1", code: "GRP-A", name: "Group A" }),
		buildEmployeeGroup({ id: "eg-2", code: "GRP-B", name: "Group B" }),
	];
	for (const group of seedGroups) employeeGroups.set(group.id, group);

	const handlers = [
		http.get("/api/offices", () => HttpResponse.json(Array.from(offices.values()))),
		http.post("/api/offices", async ({ request }) => {
			if (options.createError) {
				return HttpResponse.json(options.createError.body, { status: options.createError.status });
			}
			const body = (await request.json()) as OfficeCreate;
			const exists = Array.from(offices.values()).some((item) => item.code === body.code);
			if (exists) {
				return HttpResponse.json(
					{ detail: "Office code already exists", error: "ConflictError" },
					{ status: 409 },
				);
			}
			const created = buildOffice({
				id: `office-new-${offices.size + 1}`,
				code: body.code,
				name: body.name,
				jurisdiction: body.jurisdiction,
			});
			offices.set(created.id, created);
			return HttpResponse.json(created, { status: 201 });
		}),
		http.patch("/api/offices/:officeId", async ({ params, request }) => {
			const officeId = String(params.officeId);
			const existing = offices.get(officeId);
			if (!existing) {
				return HttpResponse.json({ detail: "Not found" }, { status: 404 });
			}
			const body = (await request.json()) as OfficeUpdate;
			const updated: OfficeResponse = {
				...existing,
				name: body.name ?? existing.name,
				jurisdiction: body.jurisdiction ?? existing.jurisdiction,
				updated_at: NOW,
			};
			offices.set(officeId, updated);
			return HttpResponse.json(updated);
		}),

		http.get("/api/payroll-units", () => HttpResponse.json(Array.from(payrollUnits.values()))),
		http.post("/api/payroll-units", async ({ request }) => {
			if (options.createError) {
				return HttpResponse.json(options.createError.body, { status: options.createError.status });
			}
			const body = (await request.json()) as PayrollUnitCreate;
			const exists = Array.from(payrollUnits.values()).some((item) => item.code === body.code);
			if (exists) {
				return HttpResponse.json(
					{ detail: "Payroll unit code already exists", error: "ConflictError" },
					{ status: 409 },
				);
			}
			const created = buildPayrollUnit({
				id: `pu-new-${payrollUnits.size + 1}`,
				code: body.code,
				name: body.name,
			});
			payrollUnits.set(created.id, created);
			return HttpResponse.json(created, { status: 201 });
		}),
		http.patch("/api/payroll-units/:payrollUnitId", async ({ params, request }) => {
			const payrollUnitId = String(params.payrollUnitId);
			const existing = payrollUnits.get(payrollUnitId);
			if (!existing) {
				return HttpResponse.json({ detail: "Not found" }, { status: 404 });
			}
			const body = (await request.json()) as PayrollUnitUpdate;
			const updated: PayrollUnitResponse = {
				...existing,
				name: body.name ?? existing.name,
				updated_at: NOW,
			};
			payrollUnits.set(payrollUnitId, updated);
			return HttpResponse.json(updated);
		}),

		http.get("/api/posts", () => HttpResponse.json(Array.from(posts.values()))),
		http.post("/api/posts", async ({ request }) => {
			if (options.createError) {
				return HttpResponse.json(options.createError.body, { status: options.createError.status });
			}
			const body = (await request.json()) as PostCreate;
			const exists = Array.from(posts.values()).some(
				(item) => item.designation === body.designation,
			);
			if (exists) {
				return HttpResponse.json(
					{ detail: "Post designation already exists", error: "ConflictError" },
					{ status: 409 },
				);
			}
			const created = buildPost({
				id: `post-new-${posts.size + 1}`,
				designation: body.designation,
				class_name: body.class_name,
			});
			posts.set(created.id, created);
			return HttpResponse.json(created, { status: 201 });
		}),
		http.patch("/api/posts/:postId", async ({ params, request }) => {
			const postId = String(params.postId);
			const existing = posts.get(postId);
			if (!existing) {
				return HttpResponse.json({ detail: "Not found" }, { status: 404 });
			}
			const body = (await request.json()) as PostUpdate;
			const updated: PostResponse = {
				...existing,
				class_name: body.class_name ?? existing.class_name,
				updated_at: NOW,
			};
			posts.set(postId, updated);
			return HttpResponse.json(updated);
		}),

		http.get("/api/employee-groups", () => HttpResponse.json(Array.from(employeeGroups.values()))),
		http.post("/api/employee-groups", async ({ request }) => {
			if (options.createError) {
				return HttpResponse.json(options.createError.body, { status: options.createError.status });
			}
			const body = (await request.json()) as EmployeeGroupCreate;
			const exists = Array.from(employeeGroups.values()).some((item) => item.code === body.code);
			if (exists) {
				return HttpResponse.json(
					{ detail: "Employee group code already exists", error: "ConflictError" },
					{ status: 409 },
				);
			}
			const created = buildEmployeeGroup({
				id: `eg-new-${employeeGroups.size + 1}`,
				code: body.code,
				name: body.name,
			});
			employeeGroups.set(created.id, created);
			return HttpResponse.json(created, { status: 201 });
		}),
		http.patch("/api/employee-groups/:employeeGroupId", async ({ params, request }) => {
			const employeeGroupId = String(params.employeeGroupId);
			const existing = employeeGroups.get(employeeGroupId);
			if (!existing) {
				return HttpResponse.json({ detail: "Not found" }, { status: 404 });
			}
			const body = (await request.json()) as EmployeeGroupUpdate;
			const updated: EmployeeGroupResponse = {
				...existing,
				name: body.name ?? existing.name,
				updated_at: NOW,
			};
			employeeGroups.set(employeeGroupId, updated);
			return HttpResponse.json(updated);
		}),
	];

	return {
		handlers,
		stores: { offices, payrollUnits, posts, employeeGroups },
	};
}
