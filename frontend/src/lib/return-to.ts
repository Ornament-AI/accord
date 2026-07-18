/**
 * Sanitize a post-login return path so it can only be an in-app relative path.
 * Rejects protocol-relative URLs (`//evil`) and absolute URLs.
 */
export function sanitizeReturnTo(value: string | null | undefined): string {
	if (!value) return "/";
	if (!value.startsWith("/") || value.startsWith("//")) return "/";
	if (value.includes("://")) return "/";
	return value;
}
