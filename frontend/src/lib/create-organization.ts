import { ApiError } from "@/lib/errors";
import {
	organizationSlugCandidate,
	randomSlugDisambiguator,
} from "@/lib/organization-slug";

const SLUG_CONFLICT_ATTEMPTS = 5;

type CreateOrganizationFn = (input: { name: string; slug: string }) => Promise<unknown>;

/**
 * Create an organization from a display name, generating and disambiguating
 * the slug without exposing it to the caller.
 */
export async function createOrganizationFromName(
	createOrganization: CreateOrganizationFn,
	name: string,
): Promise<void> {
	const trimmedName = name.trim();
	if (!trimmedName) {
		throw new Error("Name is required.");
	}

	let disambiguator: string | undefined;
	for (let attempt = 0; attempt < SLUG_CONFLICT_ATTEMPTS; attempt++) {
		const slug = organizationSlugCandidate(trimmedName, disambiguator);
		try {
			await createOrganization({ name: trimmedName, slug });
			return;
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				disambiguator = randomSlugDisambiguator();
				continue;
			}
			throw error;
		}
	}

	throw new Error("Unable to create organization right now. Please try a different name.");
}
