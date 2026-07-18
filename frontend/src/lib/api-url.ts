const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim() ?? "";
const apiBaseUrl = configuredApiBaseUrl.replace(/\/+$/, "");

export function resolveApiUrl(path: string): string {
	if (!apiBaseUrl || /^https?:\/\//i.test(path)) {
		return path;
	}
	return path.startsWith("/") ? `${apiBaseUrl}${path}` : `${apiBaseUrl}/${path}`;
}
