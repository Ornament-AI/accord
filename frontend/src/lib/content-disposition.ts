/**
 * Parse a filename from a Content-Disposition header value.
 * Supports RFC 5987 `filename*=UTF-8''...`, quoted `filename="..."`, and plain `filename=...`.
 */
export function parseContentDispositionFilename(disposition: string | null): string | null {
	if (!disposition) return null;

	const encoded = /(?:^|;)\s*filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
	if (encoded) {
		try {
			return decodeURIComponent(encoded).trim() || null;
		} catch {
			return encoded.trim() || null;
		}
	}

	const quoted = /(?:^|;)\s*filename="([^"]+)"/i.exec(disposition)?.[1];
	if (quoted) return quoted.trim() || null;

	const plain = /(?:^|;)\s*filename=([^;]+)/i.exec(disposition)?.[1];
	return plain?.trim().replace(/^"|"$/g, "") || null;
}
