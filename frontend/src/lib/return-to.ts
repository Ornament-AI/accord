/**
 * Sanitize a post-login return path so it can only be an in-app relative path.
 * Rejects protocol-relative URLs, absolute URLs, backslashes, and controls.
 */
export function sanitizeReturnTo(value: string | null | undefined): string {
	if (!value) return "/";
	if (!value.startsWith("/") || value.startsWith("//")) return "/";
	if (value.includes("://")) return "/";
	if (value.includes("\\") || Array.from(value).some((char) => char.charCodeAt(0) < 32)) return "/";
	return value;
}
