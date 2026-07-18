/** Reserved slugs mirrored from backend `app.services.organizations.RESERVED_SLUGS`. */
const RESERVED_SLUGS = new Set(["api", "admin", "app", "auth", "www"]);

const MIN_SLUG_LENGTH = 2;
const MAX_SLUG_LENGTH = 50;

/** Derive a URL-safe organization slug from a display name. */
export function suggestOrganizationSlug(name: string): string {
	let slug = name
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "-")
		.replace(/-+/g, "-")
		.replace(/^-+|-+$/g, "");

	if (slug.length > MAX_SLUG_LENGTH) {
		slug = slug.slice(0, MAX_SLUG_LENGTH).replace(/-+$/, "");
	}

	if (slug.length < MIN_SLUG_LENGTH || RESERVED_SLUGS.has(slug)) {
		return "organization";
	}

	return slug;
}

/**
 * Build a create-org slug candidate. Pass a disambiguator (e.g. short random)
 * when the base slug collided or needs uniqueness.
 */
export function organizationSlugCandidate(name: string, disambiguator?: string): string {
	const base = suggestOrganizationSlug(name);
	if (!disambiguator) return base;

	const suffix = `-${disambiguator.toLowerCase().replace(/[^a-z0-9]+/g, "")}`;
	if (suffix.length <= 1) return base;

	const maxBase = MAX_SLUG_LENGTH - suffix.length;
	let truncated = base.slice(0, Math.max(MIN_SLUG_LENGTH, maxBase)).replace(/-+$/, "");
	if (truncated.length < MIN_SLUG_LENGTH) {
		truncated = "org";
	}
	return `${truncated}${suffix}`;
}

/** Short random token for slug collision retries. */
export function randomSlugDisambiguator(length = 6): string {
	const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
	const bytes = new Uint8Array(length);
	crypto.getRandomValues(bytes);
	return Array.from(bytes, (byte) => alphabet[byte % alphabet.length]).join("");
}
