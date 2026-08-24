import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/errors";

const MAX_QUERY_RETRIES = 2;
const RETRYABLE_CLIENT_STATUSES = new Set([408, 429]);

export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
	if (failureCount >= MAX_QUERY_RETRIES) return false;
	if (!(error instanceof ApiError)) return true;
	if (error.status === 0) return true;
	if (RETRYABLE_CLIENT_STATUSES.has(error.status)) return true;
	return error.status >= 500;
}

export const queryClient = new QueryClient({
	defaultOptions: {
		queries: {
			staleTime: 30_000,
			gcTime: 30 * 60_000,
			retry: shouldRetryQuery,
			retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30_000),
			refetchOnWindowFocus: true,
			refetchOnMount: true,
			refetchOnReconnect: true,
		},
		mutations: {
			retry: 0,
		},
	},
});
