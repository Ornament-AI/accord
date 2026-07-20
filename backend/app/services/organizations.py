"""Organization helpers (slug validation). Create path lives in bootstrap (ADR 0011)."""

from __future__ import annotations

import re

from app.exceptions import ValidationError

RESERVED_SLUGS = frozenset({"api", "admin", "app", "auth", "www"})
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def validate_slug(slug: str) -> None:
    """Raise ValidationError if slug is reserved, malformed, or out of length bounds."""
    if not isinstance(slug, str) or not (2 <= len(slug) <= 50):
        raise ValidationError("Slug must be between 2 and 50 characters.")
    if not SLUG_RE.fullmatch(slug):
        raise ValidationError(
            "Slug must be lowercase kebab-case (letters, digits, and single hyphens)."
        )
    if slug in RESERVED_SLUGS:
        raise ValidationError(f"Slug '{slug}' is reserved.")
