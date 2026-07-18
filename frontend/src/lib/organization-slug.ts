/** Derive a URL-safe organization slug from a display name. */
export function suggestOrganizationSlug(name: string): string {
	return name
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "-")
		.replace(/-+/g, "-")
		.replace(/^-+|-+$/g, "");
}
