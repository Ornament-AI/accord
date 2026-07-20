import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJson } from "@/lib/api/http";
import type { components } from "@/types/api.generated";

export type OfficeResponse = components["schemas"]["OfficeResponse"];
export type OfficeCreate = components["schemas"]["OfficeCreate"];
export type OfficeUpdate = components["schemas"]["OfficeUpdate"];

export type PostResponse = components["schemas"]["PostResponse"];
export type PostCreate = components["schemas"]["PostCreate"];
export type PostUpdate = components["schemas"]["PostUpdate"];

export type OfficeJurisdiction = OfficeCreate["jurisdiction"];

export const orgStructureQueryKeys = {
	all: () => ["org-structure"] as const,
	offices: () => ["org-structure", "offices"] as const,
	posts: () => ["org-structure", "posts"] as const,
};

export function listOffices() {
	return fetchJson<OfficeResponse[]>("/api/offices");
}

export function createOffice(body: OfficeCreate) {
	return fetchJson<OfficeResponse>("/api/offices", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function updateOffice(officeId: string, body: OfficeUpdate) {
	return fetchJson<OfficeResponse>(`/api/offices/${officeId}`, {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function listPosts() {
	return fetchJson<PostResponse[]>("/api/posts");
}

export function createPost(body: PostCreate) {
	return fetchJson<PostResponse>("/api/posts", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function updatePost(postId: string, body: PostUpdate) {
	return fetchJson<PostResponse>(`/api/posts/${postId}`, {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
	});
}

export function useOfficesList() {
	return useQuery({
		queryKey: orgStructureQueryKeys.offices(),
		queryFn: listOffices,
	});
}

export function useCreateOffice() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: createOffice,
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: orgStructureQueryKeys.offices() });
		},
	});
}

export function useUpdateOffice() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({ officeId, body }: { officeId: string; body: OfficeUpdate }) =>
			updateOffice(officeId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: orgStructureQueryKeys.offices() });
		},
	});
}

export function usePostsList() {
	return useQuery({
		queryKey: orgStructureQueryKeys.posts(),
		queryFn: listPosts,
	});
}

export function useCreatePost() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: createPost,
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: orgStructureQueryKeys.posts() });
		},
	});
}

export function useUpdatePost() {
	const queryClient = useQueryClient();
	return useMutation({
		mutationFn: ({ postId, body }: { postId: string; body: PostUpdate }) =>
			updatePost(postId, body),
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: orgStructureQueryKeys.posts() });
		},
	});
}
